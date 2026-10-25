"""Building the golden memory store, and scoring a retrieval engine on the question set."""

import time
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import LlmCallOrigin, MessageSource
from app.domain.retrieval import RetrievalQuery
from app.integrations.llm_calls import LlmCallContext
from app.models.memory import Memory
from app.repositories.memory_repository import owned_by
from app.schemas.raw_message import RawMessageCreate
from app.services.ingestion import IngestionService
from app.services.processing.runner import PipelineRunner
from app.services.retrieval.engine import RetrievalEngine
from evaluation.golden import GoldenCase
from evaluation.retrieval.dataset import QueryCategory, RetrievalCase, relevant_summaries
from evaluation.retrieval.metrics import (
    hit_at,
    mean,
    ndcg_at,
    precision_at,
    recall_at,
    reciprocal_rank,
)

# The dataset's timestamps are local times of its author, who writes from India.
GOLDEN_TIMEZONE: Final = timezone(timedelta(hours=5, minutes=30))
K_VALUES: Final = (1, 3, 5, 10)
_INGEST_BATCH: Final = 50


def golden_unit(case: GoldenCase) -> list[RawMessageCreate]:
    return [
        RawMessageCreate(
            source=MessageSource.WHATSAPP_IMPORT,
            content=message.content,
            source_message_id=message.event_id,
            source_created_at=message.sent_at_local.replace(tzinfo=GOLDEN_TIMEZONE),
        )
        for message in case.input.messages
    ]


async def build_golden_store(
    ingestion: IngestionService,
    runner: PipelineRunner,
    cases: Sequence[GoldenCase],
    *,
    owner_id: uuid.UUID | None = None,
) -> None:
    """Capture and process every golden unit once. Cases sharing an input are one unit,
    answered with all their expected memories by the fixture extractor."""
    units: dict[tuple[str, ...], GoldenCase] = {}
    for case in cases:
        units.setdefault(case.unit_key, case)
    pending = list(units.values())
    run_ids: list[uuid.UUID] = []
    for start in range(0, len(pending), _INGEST_BATCH):
        batch = pending[start : start + _INGEST_BATCH]
        ingested = await ingestion.ingest([golden_unit(case) for case in batch], owner_id=owner_id)
        run_ids.extend(unit.run.id for unit in ingested)
    await runner.process_runs(run_ids)


async def memories_by_content(
    session_factory: async_sessionmaker[AsyncSession], *, owner_id: uuid.UUID | None = None
) -> dict[str, list[uuid.UUID]]:
    async with session_factory() as session:
        rows = await session.execute(
            select(Memory.id, Memory.content).where(owned_by(Memory.owner_id, owner_id))
        )
    index: dict[str, list[uuid.UUID]] = defaultdict(list)
    for memory_id, content in rows:
        index[content].append(memory_id)
    return dict(index)


@dataclass(frozen=True, slots=True)
class QueryResult:
    case: RetrievalCase
    ranked: tuple[uuid.UUID, ...]
    relevant: frozenset[uuid.UUID]
    duration_ms: int
    degraded: bool
    candidates: Mapping[str, int]
    metrics: Mapping[str, float]

    @property
    def missed(self) -> frozenset[uuid.UUID]:
        return self.relevant - frozenset(self.ranked)


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    results: tuple[QueryResult, ...]
    embedding_space: str | None
    reranked: bool
    k_values: tuple[int, ...] = field(default=K_VALUES)

    def summary(self) -> dict[str, dict[str, float | None]]:
        """Mean metrics per category, and over every answerable question ("all")."""
        groups: dict[str, list[QueryResult]] = defaultdict(list)
        for result in self.results:
            groups[result.case.category.value].append(result)
            if result.case.category is not QueryCategory.NEGATIVE:
                groups["all"].append(result)
        summary: dict[str, dict[str, float | None]] = {}
        for name, results in sorted(groups.items()):
            names = sorted({metric for result in results for metric in result.metrics})
            summary[name] = {
                metric: mean(
                    [result.metrics[metric] for result in results if metric in result.metrics]
                )
                for metric in names
            }
            summary[name]["queries"] = float(len(results))
            summary[name]["mean_duration_ms"] = mean([float(r.duration_ms) for r in results])
        return summary


async def evaluate(
    engine: RetrievalEngine,
    cases: Sequence[RetrievalCase],
    golden: Sequence[GoldenCase],
    content_index: Mapping[str, Sequence[uuid.UUID]],
    *,
    owner_id: uuid.UUID | None = None,
    k_values: tuple[int, ...] = K_VALUES,
) -> RetrievalEvaluation:
    """Run every question and score it. Raises when a relevant memory is not in the store,
    which means the store was not built from this golden dataset."""
    golden_by_id = {case.case_id: case for case in golden}
    limit = max(k_values)
    results: list[QueryResult] = []
    embedding_space: str | None = None
    reranked = False
    for case in cases:
        relevant: set[uuid.UUID] = set()
        for summary in relevant_summaries(case, golden_by_id):
            ids = content_index.get(summary)
            if not ids:
                raise LookupError(f"{case.query_id}: no stored memory reads {summary!r}")
            relevant.update(ids)
        started = time.monotonic()
        result = await engine.search(
            RetrievalQuery(text=case.query, owner_id=owner_id, limit=limit),
            context=LlmCallContext(origin=LlmCallOrigin.RETRIEVAL, user_id=owner_id),
        )
        duration_ms = round((time.monotonic() - started) * 1000)
        embedding_space = result.embedding_space
        reranked = reranked or result.reranked
        ranked = tuple(item.memory.id for item in result.items)
        results.append(
            QueryResult(
                case=case,
                ranked=ranked,
                relevant=frozenset(relevant),
                duration_ms=duration_ms,
                degraded=result.degraded,
                candidates={str(leg.leg): leg.candidates for leg in result.legs},
                metrics=_metrics(ranked, frozenset(relevant), k_values),
            )
        )
    return RetrievalEvaluation(
        results=tuple(results),
        embedding_space=embedding_space,
        reranked=reranked,
        k_values=k_values,
    )


def _metrics(
    ranked: Sequence[uuid.UUID], relevant: frozenset[uuid.UUID], k_values: tuple[int, ...]
) -> dict[str, float]:
    if not relevant:
        # A question nothing answers: clean when nothing came back.
        return {"clean": 1.0 if not ranked else 0.0}
    metrics = {"mrr": reciprocal_rank(ranked, relevant)}
    for k in k_values:
        metrics[f"recall@{k}"] = recall_at(ranked, relevant, k)
        metrics[f"precision@{k}"] = precision_at(ranked, relevant, k)
        metrics[f"hit@{k}"] = hit_at(ranked, relevant, k)
        metrics[f"ndcg@{k}"] = ndcg_at(ranked, relevant, k)
    return metrics


def render_markdown(evaluation: RetrievalEvaluation, contents: Mapping[uuid.UUID, str]) -> str:
    """A report: metrics per category, then every question that missed an answer."""
    summary = evaluation.summary()
    lines = [
        "# Retrieval evaluation",
        "",
        f"Embedding space: {evaluation.embedding_space or 'none (words and names only)'}. "
        f"Reranked: {'yes' if evaluation.reranked else 'no'}.",
        "",
        "| Category | Queries | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Clean | ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, values in summary.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    _number(values.get("queries"), 0),
                    _number(values.get("recall@1")),
                    _number(values.get("recall@5")),
                    _number(values.get("recall@10")),
                    _number(values.get("mrr")),
                    _number(values.get("ndcg@10")),
                    _number(values.get("clean")),
                    _number(values.get("mean_duration_ms"), 0),
                ]
            )
            + " |"
        )
    misses = [
        result
        for result in evaluation.results
        if result.missed or result.metrics.get("clean") == 0.0
    ]
    if misses:
        lines += ["", "## Questions with a missed or a wrong answer", ""]
        for result in misses:
            lines.append(
                f"- **{result.case.query_id}** ({result.case.category.value}): {result.case.query}"
            )
            for memory_id in sorted(result.missed, key=str):
                lines.append(f"  - missed: {contents.get(memory_id, memory_id)}")
            if not result.relevant:
                for memory_id in result.ranked[:3]:
                    lines.append(f"  - returned: {contents.get(memory_id, memory_id)}")
    return "\n".join(lines) + "\n"


def _number(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"
