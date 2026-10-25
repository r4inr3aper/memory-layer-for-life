"""System corrections to extractor output are applied before storage and are recorded."""

from app.domain.enums import MemoryType, ProcessingStatus
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from tests.integration.conftest import HarnessFactory
from tests.support.extraction import ScriptedExtractor, evidence, extraction, financial, memory


async def test_a_miscalculated_amount_is_corrected_before_it_is_stored(
    make_harness: HarnessFactory,
) -> None:
    """The extractor copies the sum correctly but adds it up wrong."""
    extractor = ScriptedExtractor(
        extraction(
            memory(
                "Written sum 245+131+200+135",
                memory_type=MemoryType.FINANCIAL_NOTE,
                evidence_refs=[evidence(0, "245+131+200+135")],
                financial=financial(
                    611, component_amounts=[245, 131, 200, 135], calculation="245+131+200+135"
                ),
            )
        )
    )
    harness = make_harness(extractor)

    _, outcome = await harness.ingest_and_process("245+131+200+135")

    assert outcome.status is ProcessingStatus.SUCCEEDED
    (stored,) = await harness.rows(Memory)
    assert stored.metadata_["financial"]["amount"] == 711
    (result,) = await harness.rows(ExtractionResult)
    assert result.payload["output"]["memories"][0]["financial"]["amount"] == 711
    # The change to the extractor's output is on record.
    assert result.metadata_["corrections"] == [
        "memory 0: amount recomputed from the written calculation"
    ]


async def test_an_untouched_extraction_records_no_correction(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())

    await harness.ingest_and_process("buy milk")

    (result,) = await harness.rows(ExtractionResult)
    assert "corrections" not in result.metadata_
