"""Deterministic evaluation of simple arithmetic written in a note.

People write sums such as ``232+104`` or ``400/2`` in their notes. A language model that
copies such an expression can still get the result wrong, so the result is never taken
from the model: it is computed here.

Only plain numbers, ``+ - * /``, and parentheses are understood. Anything else, such as
``4x 170`` or ``12-15 June``, is not arithmetic for this module and yields ``None``. The
text is parsed, never executed.
"""

import re
from typing import Final

_MAX_EXPRESSION_LENGTH: Final = 200
_MAX_NESTING: Final = 20
_TOKEN: Final = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([-+*/()]))")


class _NotArithmeticError(Exception):
    """The text is not an arithmetic expression this module understands."""


class _Parser:
    """Recursive descent over ``expression := term (('+' | '-') term)*``."""

    def __init__(self, tokens: list[float | str]) -> None:
        self._tokens = tokens
        self._position = 0
        self._depth = 0

    def parse(self) -> float:
        value = self._expression()
        if self._position != len(self._tokens):
            raise _NotArithmeticError
        return value

    def _peek(self) -> float | str | None:
        return self._tokens[self._position] if self._position < len(self._tokens) else None

    def _take(self) -> float | str:
        token = self._peek()
        if token is None:
            raise _NotArithmeticError
        self._position += 1
        return token

    def _expression(self) -> float:
        value = self._term()
        while self._peek() in ("+", "-"):
            operator = self._take()
            operand = self._term()
            value = value + operand if operator == "+" else value - operand
        return value

    def _term(self) -> float:
        value = self._factor()
        while self._peek() in ("*", "/"):
            operator = self._take()
            operand = self._factor()
            if operator == "/":
                if operand == 0:
                    raise _NotArithmeticError
                value /= operand
            else:
                value *= operand
        return value

    def _factor(self) -> float:
        token = self._take()
        if isinstance(token, float):
            return token
        if token == "-":
            return -self._factor()
        if token == "(":
            self._depth += 1
            if self._depth > _MAX_NESTING:
                raise _NotArithmeticError
            value = self._expression()
            if self._take() != ")":
                raise _NotArithmeticError
            self._depth -= 1
            return value
        raise _NotArithmeticError


def _tokenize(expression: str) -> list[float | str]:
    tokens: list[float | str] = []
    position = 0
    text = expression.rstrip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise _NotArithmeticError
        number, operator = match.groups()
        tokens.append(float(number) if number is not None else operator)
        position = match.end()
    return tokens


def evaluate_arithmetic(expression: str) -> float | None:
    """Return the value of an arithmetic expression, or ``None`` if the text is not one.

    A lone number is not a calculation and also yields ``None``. So does a division by
    zero, and any text containing something other than numbers, operators, and
    parentheses.
    """
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        return None
    try:
        tokens = _tokenize(expression)
        if not any(token in ("+", "-", "*", "/") for token in tokens):
            return None
        return _Parser(tokens).parse()
    except _NotArithmeticError:
        return None
