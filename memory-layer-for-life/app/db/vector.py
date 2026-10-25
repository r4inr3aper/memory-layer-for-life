"""pgvector's ``vector`` column type, without a database-driver codec.

asyncpg has no codec for pgvector, so a vector crosses the wire as text: a bound value is
written as ``[0.1,0.2,...]``, sent as text, and cast to ``vector`` in the statement itself.
No connection needs setting up, and no extra package is involved.

The column has no fixed dimension: each embedding space has its own, enforced by a check
constraint and by every query (see ``MemoryEmbedding``). Vectors are never read back into
Python; distances are computed in SQL, so the column is deferred on the model.
"""

import math
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Float, String, cast, literal
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import BindParameter, ColumnElement
from sqlalchemy.types import UserDefinedType


def format_vector(values: Sequence[float]) -> str:
    """The text form PostgreSQL parses as a vector. Rejects what pgvector would reject
    less clearly: empty vectors and non-finite numbers."""
    if not values:
        raise ValueError("A vector needs at least one dimension.")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("A vector holds finite numbers only.")
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def parse_vector(text: str) -> list[float]:
    body = text.strip().removeprefix("[").removesuffix("]")
    return [float(part) for part in body.split(",")] if body else []


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector"

    def bind_processor(self, dialect: Dialect) -> Callable[[Any], str | None]:
        def process(value: Any) -> str | None:
            return None if value is None else format_vector(value)

        return process

    def bind_expression(self, bindvalue: BindParameter[Any]) -> ColumnElement[Any]:
        # Sent as text, read as a vector by PostgreSQL.
        return cast(cast(bindvalue, String), self)

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[[Any], list[float] | None]:
        def process(value: Any) -> list[float] | None:
            if value is None or isinstance(value, list):
                return value
            return parse_vector(str(value))

        return process


def cosine_distance(
    column: ColumnElement[Any] | InstrumentedAttribute[Any], values: Sequence[float]
) -> ColumnElement[float]:
    """pgvector's ``<=>`` between a vector column and a vector: 1 minus the cosine
    similarity, from 0 (same direction) to 2 (opposite)."""
    query = literal(list(values), type_=Vector())
    distance: ColumnElement[float] = column.op("<=>", return_type=Float)(query)
    return distance
