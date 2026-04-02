"""Math instructions (type marker 0x271A).

Binary class name: ``"Math"``.

The math instruction evaluates a user-defined formula and stores the
result in a destination register.  Two modes: decimal (trig, log, etc.)
and hex (bitwise AND/OR/XOR, shift/rotate).

The binary blob is always 1010 tagged fields:

- 9 header fields (result, flags, formula strings, func code)
- 500 operand slots (tag 0x6888, indexed sentinel)
- 500 reserved slots (tag 0x688C, indexed sentinel, always empty)
- 1 terminator (tag 0x0000)

CSV token format::

    math(DS65 + DS66, DS67, mode=decimal)
    math(DH1 + DH2, DH3, mode=hex)
    math(DS68 * DS69, DS70, mode=decimal, oneshot=1)

The CSV expression syntax matches Click's formula pad exactly:
uppercase function names (``SIN``, ``COS``, …), Click operators
(``+``, ``-``, ``*``, ``/``, ``^``, ``MOD``, ``AND``, ``OR``,
``XOR``), spaces around operators.  No conversion needed — the
expression is stored verbatim in the binary.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..model import AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code table
# ---------------------------------------------------------------------------

MATH_FUNC_CODES: dict[tuple[str, bool], str] = {
    ("decimal", False): "8451",
    ("decimal", True): "8452",
    ("hex", False): "8453",
    ("hex", True): "8454",
}

_FUNC_TO_MODE: dict[str, tuple[str, bool]] = {v: k for k, v in MATH_FUNC_CODES.items()}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_TAG_RESULT = 0x6065
_TAG_HEX_FLAG = 0x11FE
_TAG_ONESHOT = 0x11F8
_TAG_TEMPLATE_DISPLAY = 0x61FF
_TAG_FORMULA_DISPLAY = 0x6228
_TAG_TEMPLATE_INTERNAL = 0x6229
_TAG_FORMULA_INTERNAL = 0x61FD
_TAG_FUNC_CODE = 0x3218
_TAG_NICKNAME_FLAG = 0x2224
_TAG_OPERAND = 0x6888
_TAG_RESERVED = 0x688C
_TAG_TERMINATOR = 0x0000

_HEADER_TAGS = (
    _TAG_RESULT,
    _TAG_HEX_FLAG,
    _TAG_ONESHOT,
    _TAG_TEMPLATE_DISPLAY,
    _TAG_FORMULA_DISPLAY,
    _TAG_TEMPLATE_INTERNAL,
    _TAG_FORMULA_INTERNAL,
    _TAG_FUNC_CODE,
    _TAG_NICKNAME_FLAG,
)

_OPERAND_SLOTS = 500
_RESERVED_SLOTS = 500
_TOTAL_FIELDS = 9 + _OPERAND_SLOTS + _RESERVED_SLOTS + 1  # 1010

# ---------------------------------------------------------------------------
# Expression tokenizer — extracts operands from a formula string
# ---------------------------------------------------------------------------

#: Click PLC memory address pattern.
_ADDR_RE = re.compile(r"\b(CTD|CT|TD|TXT|SC|SD|DS|DD|DH|DF|X|Y|C|T)\d+\b")

#: Reserved function/operator names that must NOT be treated as operands.
RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "LOG",
        "SUM",
        "SIN",
        "ASIN",
        "RAD",
        "COS",
        "ACOS",
        "SQRT",
        "DEG",
        "TAN",
        "ATAN",
        "LN",
        "PI",
        "MOD",
        "AND",
        "OR",
        "XOR",
        "LSH",
        "RSH",
        "LRO",
        "RRO",
    }
)


def _normalize_parens(expr: str) -> str:
    """Ensure spaces around parentheses: ``(x)`` → ``( x )``."""
    expr = re.sub(r"\(\s*", "( ", expr)
    expr = re.sub(r"\s*\)", " )", expr)
    # Collapse any double spaces introduced by already-spaced input.
    return re.sub(r"  +", " ", expr).strip()


def _extract_operands(expression: str) -> list[str]:
    """Extract operand addresses from *expression*, in order of appearance.

    Preserves duplicates — each occurrence gets its own operand slot.
    Skips reserved function names (``SIN``, ``MOD``, etc.) and hex
    literal suffixes.
    """
    result: list[str] = []
    for m in _ADDR_RE.finditer(expression):
        addr = m.group(0)
        if addr.upper() in RESERVED_NAMES:
            continue
        result.append(addr)
    return result


def _make_template(expression: str, operands: list[str]) -> str:
    """Replace operand addresses with ``@`` placeholders.

    Longer addresses are replaced first to avoid partial matches
    (e.g. ``DS10`` before ``DS1``).
    """
    result = expression
    for addr in sorted(operands, key=lambda s: -len(s)):
        result = result.replace(addr, "@")
    return result


def _make_internal(expression: str) -> str:
    """Convert display-form expression to Click internal form.

    Replaces spaces with ``#`` delimiters and prefixes standalone
    numeric literals with ``H`` (Click's internal normalization).
    """
    tokens = expression.split(" ")
    return "#".join(f"H{t}" if re.fullmatch(r"\d+", t) else t for t in tokens)


def _reconstruct_expression(template_display: str, formula_internal: str) -> str:
    """Rebuild a canonical expression from display literals + internal operands.

    Click stores two useful math formula views:

    - ``template_display`` keeps the user's literal formatting but replaces
      operands with ``@`` placeholders.
    - ``formula_internal`` keeps concrete operands but normalizes literals
      (for example ``200`` may become ``H200``).

    There is also a display-expression field in native blobs that may be
    nickname-expanded (for example ``<tag_name> + 200``).  Canonical CSV
    deliberately ignores that richer display form for now; if we later add a
    ``preserve_math_display``-style option, that field is the right source to
    expose alongside the canonical expression.

    Replacing each ``@`` with the next operand occurrence from the internal
    form gives us a stable CSV expression without nickname expansion and
    without the internal-only literal normalization.
    """

    if not template_display:
        return formula_internal.replace("#", " ")

    placeholder_count = template_display.count("@")
    if placeholder_count == 0:
        return template_display

    operand_occurrences = [m.group(0) for m in _ADDR_RE.finditer(formula_internal)]
    if len(operand_occurrences) != placeholder_count:
        return formula_internal.replace("#", " ")

    parts = template_display.split("@")
    rebuilt = [parts[0]]
    for operand, suffix in zip(operand_occurrences, parts[1:], strict=True):
        rebuilt.append(operand)
        rebuilt.append(suffix)
    return "".join(rebuilt)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Math(AfInstruction):
    """A math instruction.

    Attributes
    ----------
    expression:
        The formula in Click syntax (e.g. ``"DS65 + DS66"``).
        Spaces around operators, uppercase function names.
    result:
        Destination register (e.g. ``"DS67"``).
    mode:
        ``"decimal"`` or ``"hex"``.
    oneshot:
        Execute once on OFF→ON transition.
    """

    expression: str
    result: str
    mode: Literal["decimal", "hex"] = "decimal"
    oneshot: bool = False

    def __post_init__(self) -> None:
        self.expression = _normalize_parens(self.expression)

    def to_csv(self) -> str:
        parts = [self.expression, self.result]
        kw: list[str] = [f"mode={self.mode}"]
        if self.oneshot:
            kw.append("oneshot=1")
        return f"math({','.join(parts)},{','.join(kw)})"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self, *, show_nicknames: bool = False) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field

        operands = _extract_operands(self.expression)

        # Build the 4 formula fields.
        template_display = _make_template(self.expression, operands)
        if show_nicknames:
            # Click expects operands wrapped as <?ADDR> (empty nickname form)
            # when the nickname display flag is set.  Replace longer addresses
            # first to avoid partial-match issues (e.g. DS10 before DS1).
            formula_display = self.expression
            for addr in sorted(operands, key=lambda s: -len(s)):
                formula_display = formula_display.replace(addr, f"<?{addr}>")
        else:
            formula_display = self.expression
        template_internal = _make_internal(template_display)
        formula_internal = _make_internal(self.expression)

        func_code = MATH_FUNC_CODES[(self.mode, self.oneshot)]

        out = bytearray()
        out += _utf16le_null("Math")
        out += struct.pack("<I", 0x271A)  # type marker
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", _TOTAL_FIELDS)

        # --- 9 header fields (standard sentinel) ---
        out += _tagged_field(_TAG_RESULT, self.result)
        out += _tagged_field(_TAG_HEX_FLAG, "-1" if self.mode == "hex" else "0")
        out += _tagged_field(_TAG_ONESHOT, "-1" if self.oneshot else "0")
        out += _tagged_field(_TAG_TEMPLATE_DISPLAY, template_display)
        out += _tagged_field(_TAG_FORMULA_DISPLAY, formula_display)
        out += _tagged_field(_TAG_TEMPLATE_INTERNAL, template_internal)
        out += _tagged_field(_TAG_FORMULA_INTERNAL, formula_internal)
        out += _tagged_field(_TAG_FUNC_CODE, func_code)
        out += _tagged_field(_TAG_NICKNAME_FLAG, "1" if show_nicknames else "0")

        # --- 500 operand slots (indexed sentinel) ---
        for i in range(_OPERAND_SLOTS):
            value = operands[i] if i < len(operands) else ""
            sentinel = struct.pack("<I", i)
            out += _variant_tagged_field(_TAG_OPERAND, sentinel, value)

        # --- 500 reserved slots (indexed sentinel, always empty) ---
        for i in range(_RESERVED_SLOTS):
            sentinel = struct.pack("<I", i)
            out += _variant_tagged_field(_TAG_RESERVED, sentinel, "")

        # --- Terminator ---
        out += _tagged_field(_TAG_TERMINATOR, "")

        return bytes(out)


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_MATH_TYPE_CODE = 0x271A


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Math | None:
    """Construct a Math from tag data (shared by both decoders)."""
    if class_name != "Math" or type_code != _MATH_TYPE_CODE:
        return None

    result = tags.get(0x6065, "")
    expression = _reconstruct_expression(
        tags.get(0x61FF, ""),
        tags.get(0x61FD, ""),
    ) or tags.get(0x6228, "")
    if not result or not expression:
        return None

    mode: Literal["decimal", "hex"] = "hex" if 0x11FE in tags else "decimal"
    oneshot = 0x11F8 in tags

    return Math(
        expression=expression,
        result=result,
        mode=mode,
        oneshot=oneshot,
    )


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def parse_af_call(call: AfCall) -> Math:
    """Parse an AF AST call into a Math instruction."""
    if len(call.args) != 2:
        raise ValueError(
            f"math expects 2 positional args (expression, result), got {len(call.args)}"
        )

    expression, result = call.args
    mode_arg = call.kwargs.get("mode", "decimal")
    if mode_arg == "decimal":
        mode: Literal["decimal", "hex"] = "decimal"
    elif mode_arg == "hex":
        mode = "hex"
    else:
        raise ValueError(f"math mode must be 'decimal' or 'hex', got {mode_arg!r}")

    return Math(
        expression=expression,
        result=result,
        mode=mode,
        oneshot=call.kwargs.get("oneshot") == "1",
    )


SPEC = AfInstructionFamilySpec(
    family_name="math",
    instruction_types=(Math,),
    binary_class_names=("Math",),
    from_tags=from_tags,
    csv_names=("math",),
    parse_csv_call=parse_af_call,
)
