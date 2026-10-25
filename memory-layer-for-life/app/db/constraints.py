"""Helpers that derive database CHECK constraints from the domain enums.

Models build their constraints from the enums so that the two cannot disagree.
Migrations spell the same values out literally, because a migration is a frozen record
of history. ``tests/integration/test_schema_drift.py`` fails when the models and the
migrated schema diverge.
"""

from collections.abc import Iterable
from enum import StrEnum


def enum_check(column: str, enum: type[StrEnum]) -> str:
    """SQL expression restricting ``column`` to the values of ``enum``."""
    values = ",".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"


def nullable_enum_check(column: str, enum: type[StrEnum]) -> str:
    """Like ``enum_check`` but also accepts NULL."""
    return f"{column} IS NULL OR {enum_check(column, enum)}"


def members_check(column: str, members: Iterable[StrEnum]) -> str:
    """Like ``enum_check`` for a subset of an enum, such as the values that are stored."""
    values = ",".join(f"'{member.value}'" for member in members)
    return f"{column} IN ({values})"
