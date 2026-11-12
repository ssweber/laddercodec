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

The expression is read by :mod:`.math_formula`, which follows CLICK's Math dialog: it
refuses what the dialog refuses and prints the four formula strings the blob stores.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..binary_helpers import tag_flag, tag_value
from ..model import (
    AfInstruction,
    FieldError,
    check_address,
    normalize_address,
)
from ..operands.constants import INT16_MAX, INT16_MIN
from .family import AfInstructionFamilySpec
from .math_formula import address_parts, parse, range_interiors

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

_OPERAND_SLOTS = 500
_RESERVED_SLOTS = 500
#: CLICK v4's capacity.  Its editor stops listing interiors here, whatever the formula says.
_V4_RESERVED_SLOTS = 5000
# The formula's length cap (``math_formula.MAX_INTERNAL_LENGTH``) allows at most 68
# operands, within the 500 slots.

# Pre-computed empty slot bytes: each slot is [2B tag LE][4B index LE][00 00].
# Avoids 1000 _variant_tagged_field() calls per Math instruction.
_SLOT_EMPTY_SIZE = 8
_EMPTY_OPERAND_BYTES = b"".join(
    struct.pack("<HI", _TAG_OPERAND, i) + b"\x00\x00" for i in range(_OPERAND_SLOTS)
)
_EMPTY_RESERVED_BYTES = b"".join(
    struct.pack("<HI", _TAG_RESERVED, i) + b"\x00\x00" for i in range(_RESERVED_SLOTS)
)

#: Result banks per mode (Inst_Math.dll result masks; OBJ-004).
RESULT_BANKS: dict[str, frozenset[str]] = {
    "decimal": frozenset({"DS", "DD", "DF", "TD", "CTD", "SD"}),
    "hex": frozenset({"DH", "YD"}),
}


def _range_interiors(expression: str) -> list[str]:
    """The addresses each ``A : B`` range of a display formula lists (``range_interiors``)."""
    return range_interiors(expression.split())


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

    operand_occurrences = [t for t in formula_internal.split("#") if address_parts(t)]
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
        The formula in Click syntax (e.g. ``"DS65 + DS66"``), kept as CLICK shows it: one
        space between tokens, uppercase function names, addresses in display form.  A
        formula CLICK's Math dialog refuses raises :class:`FieldError`, and so does a
        ``<nickname>``: Math takes addresses.
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
        if self.mode not in RESULT_BANKS:
            raise FieldError(f"Math.mode: {self.mode!r} is not 'decimal' or 'hex'")
        if "<" in self.expression and ">" in self.expression.split("<", 1)[1]:
            raise FieldError(
                f"Math.expression: {self.expression!r} holds a <nickname>; Math takes "
                "addresses, not nicknames (laddercodec cannot resolve a nickname to its address)"
            )
        self.result = normalize_address(self.result)
        check_address(self.result, "Math.result", RESULT_BANKS[self.mode])
        self.expression = parse(self.expression, self.mode).display

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

        formula = parse(self.expression, self.mode)
        operands = formula.operands

        # Build the 4 formula fields.
        template_display = formula.template
        # In nickname view CLICK writes an address with no nickname as <?ADDR>.
        formula_display = formula.nickname_display if show_nicknames else formula.display
        template_internal = formula.internal(template=True)
        formula_internal = formula.internal()

        func_code = MATH_FUNC_CODES[(self.mode, self.oneshot)]

        out = bytearray()
        out += _utf16le_null("Math")
        out += struct.pack("<I", 0x271A)  # type marker
        out += b"\x01\x00"  # part count
        # The 500-slot form pastes into v3 and v4; only wider ranges need v4's capacity.
        interiors = formula.range_interiors
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

    try:
        math = Math(
            expression=expression,
            result=result,
            mode=mode,
            oneshot=oneshot,
        )
    except FieldError:
        # A formula the reader refuses (nickname display text, say) decodes as raw.
        return None
    findings = _legacy_findings(tag_value(tags, 0x61FD))
    if findings:
        math._legacy_findings = findings
    return math


def _legacy_findings(formula_internal: str) -> list[tuple[str, str, str]]:
    """List the 16-bit (``H``) constants outside 16 bits in a stored formula.

    Older laddercodec wrote a decimal integer outside -32768..32767 as ``H70000``;
    CLICK runs it as its low 16 bits, as a signed value.
    """
    found = []
    for token in formula_internal.split("#"):
        body = token[1:] if token.startswith("H") else ""
        digits = body[1:] if body.startswith("-") else body
        # Older laddercodec wrote at most 11 characters (CLICK's %d length rule).
        if not digits or len(digits) > 11 or not all("0" <= c <= "9" for c in digits):
            continue
        if not INT16_MIN <= int(body) <= INT16_MAX:
            low = int(body) & 0xFFFF
            if low > INT16_MAX:
                low -= 0x10000
            found.append(("Math", token, f"it is stored as 16-bit and CLICK runs it as {low}."))
    return found


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
