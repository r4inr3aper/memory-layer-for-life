from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import Select, String, cast, func, literal, select, union_all
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository

_ALL: Final = "all"


@dataclass(frozen=True, slots=True)
class PipelineStats:
    """How much the pipeline holds, by the vocabularies that matter when inspecting it."""

    raw_messages: int
    entities: int
    runs_by_status: dict[str, int]
    extractions_by_disposition: dict[str, int]
    memories_by_type: dict[str, int]
    memories_by_status: dict[str, int]
    mentions_by_resolution: dict[str, int]


def _counted(kind: str, table: Any) -> Select[Any]:
    return select(
        literal(kind).label("kind"), literal(_ALL).label("key"), func.count().label("total")
    ).select_from(table)


def _grouped(kind: str, column: ColumnElement[Any] | InstrumentedAttribute[str]) -> Select[Any]:
    key = cast(column, String)
    return select(
        literal(kind).label("kind"), key.label("key"), func.count().label("total")
    ).group_by(key)


class PipelineStatsRepository(BaseRepository):
    async def stats(self) -> PipelineStats:
        """Count everything in one round trip to the database."""
        disposition = ExtractionResult.payload["output"]["disposition"].astext
        statement = union_all(
            _counted("raw_messages", RawMessage),
            _counted("entities", Entity),
            _grouped("runs_by_status", ProcessingRun.status),
            _grouped("extractions_by_disposition", func.coalesce(disposition, "unknown")),
            _grouped("memories_by_type", Memory.memory_type),
            _grouped("memories_by_status", Memory.status),
            _grouped("mentions_by_resolution", EntityMention.resolution_status),
        )
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for row in await self._session.execute(statement):
            counts[row.kind][row.key] = int(row.total)
        return PipelineStats(
            raw_messages=counts["raw_messages"].get(_ALL, 0),
            entities=counts["entities"].get(_ALL, 0),
            runs_by_status=dict(counts["runs_by_status"]),
            extractions_by_disposition=dict(counts["extractions_by_disposition"]),
            memories_by_type=dict(counts["memories_by_type"]),
            memories_by_status=dict(counts["memories_by_status"]),
            mentions_by_resolution=dict(counts["mentions_by_resolution"]),
        )
