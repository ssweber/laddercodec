"""Math instructions (type marker 0x271A).

Binary class name: ``"Math"``.

The math instruction evaluates a user-defined formula and stores the
result in a destination register.  Two modes: decimal (trig, log, etc.)
and hex (bitwise AND/OR/XOR, shift/rotate).

The binary blob is 1010 tagged fields:

- 9 header fields (result, flags, formula strings, func code)
- 500 operand slots (tag 0x6888, indexed sentinel)
- 500 reserved slots (tag 0x688C, indexed sentinel): interior addresses of each ``A : B`` range
  (CLICK v4 copies back 5000 reserved slots; 500 pastes into both v3 and v4, so the encoder
  writes 5000, for 5510 fields, only when the ranges have more than 500 interiors)
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

from ..binary_helpers import tag_flag, tag_value
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
#: CLICK v4's capacity.  Its editor stops listing interiors here, whatever the formula says.
_V4_RESERVED_SLOTS = 5000
# Click's formula editor accepted at most 68 operands (DS1..DS68 tested); a pasted
# 69 passes CLICK v4's check.  The blob has 500 slots.

# Pre-computed empty slot bytes: each slot is [2B tag LE][4B index LE][00 00].
# Avoids 1000 _variant_tagged_field() calls per Math instruction.
_SLOT_EMPTY_SIZE = 8
_EMPTY_OPERAND_BYTES = b"".join(
    struct.pack("<HI", _TAG_OPERAND, i) + b"\x00\x00" for i in range(_OPERAND_SLOTS)
)
_EMPTY_RESERVED_BYTES = b"".join(
    struct.pack("<HI", _TAG_RESERVED, i) + b"\x00\x00" for i in range(_RESERVED_SLOTS)
)

# ---------------------------------------------------------------------------
# Expression tokenizer — extracts operands from a formula string
# ---------------------------------------------------------------------------

#: Click PLC memory address pattern.
_ADDR_RE = re.compile(r"\b(?:(?:CTD|CT|TD|TXT|SC|SD|DS|DD|DH|DF|X|Y|C|T)\d+|(?:XD|YD)\d+u?)\b")

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


_NUMBER = r"(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+|\d+)(?![\w.])"
_HEX_CONSTANT = r"[0-9A-Fa-f]+h\b"

#: One formula token: a ``<nickname>``, a constant, a word, or a single symbol.
_TOKEN_RE = re.compile(rf"<[^>]*>|{_HEX_CONSTANT}|{_NUMBER}|\w+|\S")
_CONSTANT_RE = re.compile(rf"{_HEX_CONSTANT}|{_NUMBER}")

#: After these a ``-`` is a sign, not a subtraction.
_BEFORE_SIGN = frozenset({"(", ",", ":", "+", "-", "*", "/", "^", "MOD", "AND", "OR", "XOR"})


def _normalize_spacing(expr: str) -> str:
    """Space a formula the way Click's formula editor does, one space between tokens.

    ``ABS(x)*2`` → ``ABS ( x ) * 2``, ``RAND(1,100)`` → ``RAND ( 1 , 100 )``,
    ``SUM(DS1:DS9)`` → ``SUM ( DS1 : DS9 )``.  Click splits the internal form on
    these spaces, so ``ABS(`` would be a single unknown token.  A sign stays on its
    constant (``( -5 )``) and an exponent stays whole (``1.0E-10``), but a sign on
    an address is spaced, as Click redisplays it (``-DS1`` → ``- DS1``).
    """
    out: list[str] = []
    for token in _TOKEN_RE.findall(expr):
        is_sign = out[-1:] == ["-"] and (len(out) == 1 or out[-2] in _BEFORE_SIGN)
        if is_sign and _CONSTANT_RE.fullmatch(token):
            out[-1] = f"-{token}"
        else:
            out.append(token)
    return " ".join(out)


#: ``ADDR : ADDR`` range inside a formula (e.g. ``DS1401 : DS1410``).
_RANGE_RE = re.compile(r"\b([A-Z]+)(\d+u?) : \1(\d+u?)\b")

#: XD/YD addresses in order: ``MAX ( XD0 : XD3 )`` stores XD0u, XD1, XD2.
_XY_WORD_ORDER = ("0", "0u", "1", "2", "3", "4", "5", "6", "7", "8")


def _range_interiors(expression: str) -> list[str]:
    """Addresses strictly inside each ``A : B`` range, ranges in order.

    Click lists them in the reserved slots (tag ``0x688C``): the endpoints
    are ordinary operands, ``SUM ( DS201 : DS300 )`` stores DS202..DS299.
    """
    interiors: list[str] = []
    for m in _RANGE_RE.finditer(expression):
        prefix, start, end = m.group(1), m.group(2), m.group(3)
        if prefix in ("XD", "YD"):
            if start in _XY_WORD_ORDER and end in _XY_WORD_ORDER:
                inside = _XY_WORD_ORDER[_XY_WORD_ORDER.index(start) + 1 : _XY_WORD_ORDER.index(end)]
                interiors.extend(f"{prefix}{n}" for n in inside)
            continue
        if start.endswith("u") or end.endswith("u"):
            continue
        width = len(start) if start.startswith("0") else 0
        interiors.extend(f"{prefix}{n:0{width}d}" for n in range(int(start) + 1, int(end)))
    return interiors


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


def _make_template(expression: str) -> str:
    """Replace operand addresses with ``@`` placeholders."""
    return _ADDR_RE.sub("@", expression)


def _make_internal(expression: str) -> str:
    """Convert display-form expression to Click internal form.

    Replaces spaces with ``#`` delimiters and normalizes literals the way
    Click does: a decimal integer gets an ``H`` prefix (``200`` → ``H200``),
    ahead of its sign when negative (``( -5 )`` → ``(#H-5#)``, typed in CLICK v4;
    a bare ``#-5#`` fails its syntax check), a real gets ``F`` the same way
    (``( -2.5 )`` → ``(#F-2.5#)``, ``-1.5E+10`` → ``F-1.5E+10``, typed in v4;
    pasted ``F3.14`` passes its syntax check), a hex constant becomes ``UH`` plus its decimal value (``Ah`` → ``UH10``,
    seen when a pasted Math with ``Ah`` left as typed was reopened and OK'd
    in CLICK v4, which then passed its syntax check).
    A comma function ``F ( a , b )`` is stored infix as ``a#F#b``, with a
    trailing ``#`` when it ends the formula: ``RAND ( 1 , 100 )`` →
    ``H1#RAND#H100#``, ``RAND ( 1 , 10 ) + DS1`` → ``H1#RAND#H10#+#DS1``,
    ``LSH ( DH5 , 1h )`` → ``DH5#LSH#UH1#`` (all typed in CLICK v4).  SUM, MAX, MIN,
    MDN and AVG take a range and keep the call form (``SUM#(#DS1#:#DS3#)``), as do
    one-argument calls.  CLICK's editor refuses a comma-function argument that isn't
    one operand or constant (``LSH ( DH401 + 1h , 2h )``); pasted with an infix
    form those fail Check Program with C0114, so such a call is written as called,
    nested calls included, which passes.
    """
    tokens = expression.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        name, *call = tokens[i : i + 6]
        if name in _COMMA_FUNCTIONS and call[:1] == ["("]:
            if len(call) == 5 and call[::2] == ["(", ",", ")"]:
                out += [call[1], name, call[3]]
                i += 6
                if i == len(tokens):
                    out.append("")
                continue
            end = _call_end(tokens, i)
            out += tokens[i:end]
            i = end
            continue
        out.append(tokens[i])
        i += 1
    return "#".join(_internal_literal(t) for t in out)


#: Click's two-argument functions, ``F ( a , b )``; every other call takes one value or a range.
_COMMA_FUNCTIONS = frozenset({"RAND", "LSH", "RSH", "LRO", "RRO"})


def _call_end(tokens: list[str], i: int) -> int:
    """One past the ``)`` closing the call named at *i* (the end, if unclosed)."""
    depth = 0
    for j in range(i + 1, len(tokens)):
        if tokens[j] == "(":
            depth += 1
        elif tokens[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(tokens)


_REAL_LITERAL_RE = re.compile(r"-?(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)")


def _internal_literal(token: str) -> str:
    if re.fullmatch(r"-?\d+", token):
        return f"H{token}"
    if _REAL_LITERAL_RE.fullmatch(token):
        return f"F{token}"
    if re.fullmatch(r"[0-9A-Fa-f]+h", token):
        return f"UH{int(token[:-1], 16)}"
    return token


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
        self.expression = _normalize_spacing(self.expression)

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
        template_display = _make_template(self.expression)
        if show_nicknames:
            # Click expects operands wrapped as <?ADDR> (empty nickname form)
            # when the nickname display flag is set.
            formula_display = _ADDR_RE.sub(r"<?\g<0>>", self.expression)
        else:
            formula_display = self.expression
        template_internal = _make_internal(template_display)
        formula_internal = _make_internal(self.expression)

        func_code = MATH_FUNC_CODES[(self.mode, self.oneshot)]

        out = bytearray()
        out += _utf16le_null("Math")
        out += struct.pack("<I", 0x271A)  # type marker
        out += b"\x01\x00"  # part count
        # The 500-slot form pastes into v3 and v4; only wider ranges need v4's capacity.
        interiors = _range_interiors(self.expression)
        reserved_slots = (
            _RESERVED_SLOTS if len(interiors) <= _RESERVED_SLOTS else _V4_RESERVED_SLOTS
        )
        interiors = interiors[:reserved_slots]
        out += struct.pack("<I", 9 + _OPERAND_SLOTS + reserved_slots + 1)

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
        n_ops = len(operands)
        for i in range(n_ops):
            sentinel = struct.pack("<I", i)
            out += _variant_tagged_field(_TAG_OPERAND, sentinel, operands[i])
        out += _EMPTY_OPERAND_BYTES[n_ops * _SLOT_EMPTY_SIZE :]

        # --- reserved slots: the interior addresses of each range ---
        for i, addr in enumerate(interiors):
            out += _variant_tagged_field(_TAG_RESERVED, struct.pack("<I", i), addr)
        if reserved_slots == _RESERVED_SLOTS:
            out += _EMPTY_RESERVED_BYTES[len(interiors) * _SLOT_EMPTY_SIZE :]
        else:
            for i in range(len(interiors), reserved_slots):
                out += struct.pack("<HI", _TAG_RESERVED, i) + b"\x00\x00"

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
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Math | None:
    """Construct a Math from tag data (shared by both decoders)."""
    if class_name != "Math" or type_code != _MATH_TYPE_CODE:
        return None

    result = tag_value(tags, 0x6065)
    expression = _reconstruct_expression(
        tag_value(tags, 0x61FF),
        tag_value(tags, 0x61FD),
    ) or tag_value(tags, 0x6228)
    if not result or not expression:
        return None

    mode: Literal["decimal", "hex"] = "hex" if tag_flag(tags, 0x11FE) else "decimal"
    oneshot = tag_flag(tags, 0x11F8)

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
