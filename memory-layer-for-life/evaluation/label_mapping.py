"""Relates the golden dataset's free-form labels to the pipeline's vocabulary.

The dataset was annotated before the pipeline's taxonomy existed. Its 40 ``type`` labels
and 7 ``status`` labels are free text, several are compounds such as ``task_or_idea``,
and some labels are used by a single case. A golden label therefore maps to the *set* of
pipeline values that are a faithful reading of it. The first value of each tuple is the
closest equivalent and is what the fixture extractor uses.

This table is an interpretation and is meant to be reviewed together with the dataset.
It works at the level of labels only. It never special-cases a single test case: that
would be editing expected output under another name.

A set with one member is a strict check. A wider set says the label itself leaves the
reading open, and the note next to it says why.
"""

from typing import Final

from app.domain.enums import MemoryState, MemoryType

T = MemoryType
S = MemoryState

ACCEPTED_MEMORY_TYPES: Final[dict[str, tuple[MemoryType, ...]]] = {
    # --- Labels with one faithful reading ---------------------------------------------
    "idea": (T.IDEA,),
    "task": (T.TASK,),
    "shopping_task": (T.TASK,),
    "plan": (T.PLAN,),
    "schedule": (T.PLAN,),
    "expense_note": (T.FINANCIAL_NOTE,),
    "debt_claim": (T.FINANCIAL_NOTE,),
    "resource": (T.RESOURCE,),
    "reflection": (T.REFLECTION,),
    "open_question": (T.OPEN_LOOP,),
    "career_question": (T.OPEN_LOOP,),
    # --- Compound labels: the annotator named both readings ----------------------------
    "task_or_idea": (T.TASK, T.IDEA),
    "task_or_note": (T.TASK, T.NOTE),
    "task_or_reminder": (T.TASK, T.NOTE, T.OPEN_LOOP),
    "task_or_routine": (T.TASK, T.NOTE, T.PLAN),
    # The rationale says one of the fragments "may be an intention rather than a task".
    "task_or_plan": (T.TASK, T.PLAN, T.INTENTION),
    "idea_or_reflection": (T.IDEA, T.REFLECTION, T.NOTE),
    "idea_or_architecture_note": (T.IDEA, T.NOTE),
    # A quote kept for its own sake is a reflection; kept as a line of text it is a note.
    "quote_or_reflection": (T.REFLECTION, T.NOTE),
    # Standing rules about how to work or build are preferences; a product rule stated as
    # settled is also a decision.
    "preference_or_instruction": (T.PREFERENCE, T.DECISION),
    "principle_or_instruction": (T.PREFERENCE, T.NOTE, T.REFLECTION),
    "value_or_long_term_goal": (T.GOAL, T.INTENTION, T.REFLECTION, T.PREFERENCE),
    "event_or_reminder": (T.NOTE, T.EPISODIC_EVENT, T.TASK, T.SEMANTIC_FACT),
    # --- Notes: observations and working notes ------------------------------------------
    # "Technical" names a subject, not a function. The notes under this label include
    # descriptions, design proposals, ordered work steps, and actions to take.
    "technical_note": (T.NOTE, T.TASK, T.IDEA, T.PLAN),
    # A reported problem is an unresolved issue, or a note, or the task of fixing it.
    "technical_issue": (T.OPEN_LOOP, T.NOTE, T.TASK),
    # Status lists mix open items with a finished one.
    "work_status_note": (T.NOTE, T.OPEN_LOOP, T.TASK),
    "project_status_note": (T.NOTE, T.PLAN, T.TASK, T.OPEN_LOOP),
    "open_loop": (T.OPEN_LOOP, T.NOTE),
    "travel_context": (T.NOTE, T.EPISODIC_EVENT, T.SEMANTIC_FACT),
    # Shopping notes range from ingredient lists to priced purchases.
    "shopping_note": (T.NOTE, T.TASK, T.FINANCIAL_NOTE, T.PLAN),
    "expense_calculation": (T.FINANCIAL_NOTE, T.NOTE),
    # --- Intentions, plans, and questions with soft edges -------------------------------
    "learning_intention": (T.INTENTION, T.TASK, T.GOAL),
    "career_intention": (T.INTENTION, T.GOAL),
    "self_improvement_intention": (T.INTENTION, T.GOAL, T.COMMITMENT),
    "research_intention": (T.INTENTION, T.TASK, T.IDEA),
    "learning_plan": (T.PLAN, T.GOAL, T.INTENTION),
    "personal_plan": (T.PLAN, T.TASK, T.INTENTION, T.GOAL),
    # Questions the author framed as ideas.
    "research_question": (T.OPEN_LOOP, T.IDEA, T.INTENTION, T.TASK),
    "product_question": (T.OPEN_LOOP, T.IDEA),
    # A feature the product "will also" have: proposed, intended, or already settled.
    "product_requirement": (T.IDEA, T.NOTE, T.DECISION, T.INTENTION),
}

# Golden ``status`` describes how settled the thing is. The pipeline's ``state`` only says
# whether an action is pending, planned, or stated as done, so the relation is loose and
# is reported as a metric. The one hard rule is separate: see ``allows_done``.
ACCEPTED_STATES: Final[dict[str, tuple[MemoryState, ...]]] = {
    "open": (S.OPEN, S.PLANNED),
    "planned": (S.PLANNED, S.OPEN),
    "intention": (S.OPEN, S.NOT_APPLICABLE, S.PLANNED),
    "candidate": (S.NOT_APPLICABLE, S.OPEN, S.PLANNED),
    "observed": (S.NOT_APPLICABLE, S.DONE, S.OPEN),
    "saved_reference": (S.NOT_APPLICABLE,),
    "active_instruction_candidate": (S.NOT_APPLICABLE, S.OPEN),
}

# Only ``observed`` describes something that has already happened or is already the case.
_STATUSES_THAT_ALLOW_DONE: Final = frozenset({"observed"})


class UnmappedLabelError(KeyError):
    """The dataset uses a label this table does not cover yet."""


def accepted_memory_types(golden_type: str) -> tuple[MemoryType, ...]:
    try:
        return ACCEPTED_MEMORY_TYPES[golden_type]
    except KeyError:
        raise UnmappedLabelError(f"No mapping for golden memory type {golden_type!r}") from None


def accepted_states(golden_status: str) -> tuple[MemoryState, ...]:
    try:
        return ACCEPTED_STATES[golden_status]
    except KeyError:
        raise UnmappedLabelError(f"No mapping for golden status {golden_status!r}") from None


def allows_done(golden_status: str) -> bool:
    """Whether a memory with this expected status may be recorded as completed.

    Every other status describes something still open, planned, or merely noted, so a
    ``done`` state there would be an invented completion.
    """
    accepted_states(golden_status)
    return golden_status in _STATUSES_THAT_ALLOW_DONE
