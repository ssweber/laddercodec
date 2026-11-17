"""Token parsers for condition cells and AF output tokens."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal, cast

from ..errors import CsvError
from ..instructions.comparison import split_comparison
from ..model import OPERAND_RE
from .ast import (
    KNOWN_AF_NAMES,
    AfBlank,
    AfCall,
    AfNode,
    BlankCondition,
    ComparisonCondition,
    ConditionCellNode,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
    HorizontalWire,
    JunctionDownWire,
    VerticalPassThroughWire,
)

_EDGE_RE = re.compile(r"^(rise|fall)\((.+)\)$")
# DOTALL lets the arguments match a line break, because quoted text in a call may hold one,
# such as a Copy source "A<LF>B". _call_match refuses a line break outside the quotes.
_CALL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*|\.[A-Za-z_][A-Za-z0-9_]*)\((.*)\)$", re.DOTALL)


def _call_match(text: str) -> re.Match[str] | None:
    """Return the match of *text* as a call, or None.

    Return None if *text* is not a call, or if it has a CR or LF outside quoted text. For
    example, ``copy(DS1,<LF>DS2)`` returns None.
    """
    in_quote = False
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
        elif ch in "\r\n" and not in_quote:
            return None
    return _CALL_RE.fullmatch(text)


def _split_top_level_csv_like(value: str) -> tuple[str, ...]:
    if value.strip() == "":
        return tuple()

    parts: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    in_quote = False
    idx = 0
    while idx < len(value):
        ch = value[idx]
        if in_quote:
            if ch == '"':
                if idx + 1 < len(value) and value[idx + 1] == '"':
                    idx += 2
                    continue
                in_quote = False
            idx += 1
            continue

        if ch == '"':
            in_quote = True
            idx += 1
            continue
        if ch == "(":
            paren_depth += 1
            idx += 1
            continue
        if ch == ")":
            if paren_depth > 0:
                paren_depth -= 1
            idx += 1
            continue
        if ch == "[":
            bracket_depth += 1
            idx += 1
            continue
        if ch == "]":
            if bracket_depth > 0:
                bracket_depth -= 1
            idx += 1
            continue
        if ch == "{":
            brace_depth += 1
            idx += 1
            continue
        if ch == "}":
            if brace_depth > 0:
                brace_depth -= 1
            idx += 1
            continue
        if ch == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            parts.append(value[start:idx].strip())
            start = idx + 1

        idx += 1

    if in_quote:
        raise CsvError("Malformed AF token arguments: unmatched quote")

    parts.append(value[start:].strip())
    return tuple(parts)


def _kwarg_eq_index(seg: str) -> int:
    """Return the index of the ``=`` that separates key from value, or -1.

    Skip the ``=`` in ``==``, ``!=``, ``<=`` and ``>=``, and any ``=`` inside quotes,
    parentheses or brackets. Accept an ``=`` only if the text to its left is an identifier.
    """
    paren = bracket = 0
    in_quote = False
    idx = 0
    while idx < len(seg):
        ch = seg[idx]
        if in_quote:
            if ch == '"':
                if idx + 1 < len(seg) and seg[idx + 1] == '"':
                    idx += 2
                    continue
                in_quote = False
            idx += 1
            continue
        if ch == '"':
            in_quote = True
            idx += 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket -= 1
        elif ch == "=" and paren == 0 and bracket == 0:
            # Skip == (comparison operator)
            if idx + 1 < len(seg) and seg[idx + 1] == "=":
                idx += 2
                continue
            # Skip the = of !=, <= and >=
            if idx > 0 and seg[idx - 1] in ("!", "<", ">"):
                idx += 1
                continue
            # Key must be a simple identifier
            key = seg[:idx].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                return idx
        idx += 1
    return -1


def _decode_af_string_literal(arg: str) -> str:
    if not arg:
        return arg

    if not arg.startswith('"'):
        return arg

    if len(arg) < 2 or not arg.endswith('"'):
        raise CsvError(f"Malformed AF quoted string argument: {arg!r}")

    chars: list[str] = []
    idx = 1
    end = len(arg) - 1
    while idx < end:
        ch = arg[idx]
        if ch != '"':
            chars.append(ch)
            idx += 1
            continue

        if idx + 1 < end and arg[idx + 1] == '"':
            chars.append('"')
            idx += 2
            continue

        raise CsvError(f"Malformed AF quoted string argument: {arg!r}")

    return "".join(chars)


def _split_immediate(text: str) -> tuple[str, bool]:
    """Return *text* without its immediate suffix or wrapper, and whether it had one.

    The suffix is ``.immediate`` and the wrapper is ``immediate(...)``."""
    if text.endswith(".immediate"):
        return text[: -len(".immediate")], True
    inner = re.fullmatch(r"immediate\((.+)\)", text)
    if inner:
        return inner.group(1).strip(), True
    return text, False


def _parse_contact(token: str) -> ContactCondition | None:
    text = token.strip()
    if not text:
        return None

    negated = text.startswith("~")
    if negated:
        text = text[1:].strip()

    text, immediate = _split_immediate(text)

    if not OPERAND_RE.fullmatch(text):
        return None

    return ContactCondition(operand=text, negated=negated, immediate=immediate)


def _parse_comparison(token: str) -> ComparisonCondition | None:
    parts = split_comparison(token)
    if parts is None:
        return None
    left, op, right = parts
    return ComparisonCondition(
        left=left, op=cast(Literal["==", "!=", "<", ">", "<=", ">="], op), right=right
    )


def parse_condition_token(token: str) -> ConditionCellNode:
    text = token.strip()
    if text == "":
        return BlankCondition()
    if text == "-":
        return HorizontalWire()
    if text == "T":
        return JunctionDownWire()
    if text == "|":
        return VerticalPassThroughWire()

    # A T: or |: prefix, as in T:X001 or |:rise(X002), means a wire also runs down from the cell.
    wire_down = False
    if len(text) > 2 and text[1] == ":" and text[0] in ("T", "|"):
        wire_down = True
        text = text[2:]

    # Parse an immediate edge contact such as rise(X1).immediate as an edge condition.
    # The Contact built from it refuses it later.
    edge_text, edge_immediate = _split_immediate(text)
    edge_match = _EDGE_RE.fullmatch(edge_text)
    if edge_match:
        operand = edge_match.group(2).strip()
        if OPERAND_RE.fullmatch(operand):
            return EdgeCondition(
                kind=cast(Literal["rise", "fall"], edge_match.group(1)),
                operand=operand,
                wire_down=wire_down,
                immediate=edge_immediate,
            )
        return GenericCondition(raw=token)

    contact = _parse_contact(text)
    if contact is not None:
        if wire_down:
            contact = ContactCondition(
                operand=contact.operand,
                negated=contact.negated,
                immediate=contact.immediate,
                wire_down=True,
            )
        return contact

    comparison = _parse_comparison(text)
    if comparison is not None:
        if wire_down:
            comparison = ComparisonCondition(
                left=comparison.left,
                op=comparison.op,
                right=comparison.right,
                wire_down=True,
            )
        return comparison

    return GenericCondition(raw=token)


def parse_af_token(token: str) -> AfNode:
    text = token.strip()
    if text == "":
        return AfBlank()

    m = _call_match(text)
    if not m:
        return AfCall(name=text, args=tuple(), known=False, raw=text)

    name = m.group(1)
    args_src = m.group(2).strip()
    segments = _split_top_level_csv_like(args_src)

    positional: list[str] = []
    kwargs: dict[str, str] = {}
    in_kwargs = False
    for seg in segments:
        # The arguments of a raw(...) token are field specs such as ``rows=3`` and ``60a5=1``.
        # RawInstruction reads them from the token text, so they all stay positional here.
        eq_idx = -1 if name == "raw" else _kwarg_eq_index(seg)
        if eq_idx >= 0:
            in_kwargs = True
            key = seg[:eq_idx].strip()
            val = _decode_af_string_literal(seg[eq_idx + 1 :].strip())
            kwargs[key] = val
        else:
            if in_kwargs:
                raise CsvError(f"Positional arg after keyword arg in AF token: {token!r}")
            positional.append(seg)

    return AfCall(
        name=name,
        args=tuple(positional),
        known=name in KNOWN_AF_NAMES,
        kwargs=kwargs,
        raw=text,
    )


def fill_blank_args(token: str, fill: Callable[[int], str], *, ranges: bool = False) -> str | None:
    """Return *token*, an AF call, with each blank argument replaced by ``fill(i)``.

    Return None if no argument is blank. Also return None if *token* is not a call, or if it
    is a ``raw(...)`` token, whose arguments are field specs.

    ``i`` is the index of the top-level argument, counted from 0. A blank positional argument
    becomes ``fill(i)``, and a blank keyword value becomes ``key=fill(i)``. ``name()`` counts
    as one blank argument.

    With *ranges*, each argument is read as a range. A blank argument becomes
    ``fill(i)..fill(i)``. In a range with a blank start or end, such as ``..``, ``..DS4`` or
    ``DS1..``, each blank end becomes ``fill(i)``. ``write_csv`` writes a range in this form
    when its start or end is blank.
    """
    m = _call_match(token.strip())
    if not m or m.group(1) == "raw":
        return None
    segments = list(_split_top_level_csv_like(m.group(2).strip())) or [""]
    filled = []
    for i, seg in enumerate(segments):
        eq_idx = _kwarg_eq_index(seg)
        key, value = (seg[: eq_idx + 1], seg[eq_idx + 1 :]) if eq_idx >= 0 else ("", seg)
        blank = _filled(value.strip(), i, fill, ranges=ranges)
        filled.append(seg if blank is None else f"{key}{blank}")
    if filled == segments:
        return None
    return f"{m.group(1)}({','.join(filled)})"


def _filled(value: str, i: int, fill: Callable[[int], str], *, ranges: bool) -> str | None:
    """Return *value*, argument *i*, with each blank replaced by ``fill(i)``.

    Return None if *value* has no blank.
    """
    if not ranges:
        return fill(i) if not value else None
    start, dots, end = value.partition("..")
    if value and (not dots or (start and end)):
        return None
    return f"{start or fill(i)}..{end or fill(i)}"
