"""Math instructions (type marker 0x271A).

In the binary, the class name is ``"Math"``.

The math instruction evaluates a user-defined formula and stores the
result in a destination register.  It has two modes.  Decimal mode has
functions such as trig and log.  Hex mode has bitwise AND, OR and XOR,
and shift and rotate.

The binary blob is 1010 tagged fields:

- 9 header fields (result, flags, formula strings, func code)
- 500 operand slots (tag 0x6888, indexed sentinel)
- 500 reserved slots (tag 0x688C, indexed sentinel): the addresses between the ends of each
  ``A : B`` range
- 1 terminator (tag 0x0000)

When you copy a Math box, CLICK v4 puts 5000 reserved slots on the clipboard.  A blob with
500 reserved slots pastes into both v3 and v4.  So the encoder writes 5000 reserved slots,
for 5510 fields, only when the ranges have more than 500 addresses between their ends.

CSV token format::

    math(DS65 + DS66, DS67, mode=decimal)
    math(DH1 + DH2, DH3, mode=hex)
    math(DS68 * DS69, DS70, mode=decimal, oneshot=1)

:mod:`.math_formula` reads the expression.  It refuses what CLICK's Math dialog refuses,
and it writes the four formula strings that the blob stores.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..binary_helpers import tag_flag, tag_value
from ..codes import Code
from ..errors import CsvError
from ..model import AfInstruction, FieldError, Reason, check_address
from ..operands.address import read_as_typed
from ..operands.checks import HEX_MATH_RESULT, Refusals, check_csv_flag, check_writable_sd
from ..operands.constants import INT16_MAX, INT16_MIN
from ..operands.unchecked import read_in_another_form
from .family import AfInstructionFamilySpec
from .math_formula import address_parts, parse
from .math_formula import range_interiors as formula_range_interiors
from .raw import _decompose_blob

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
RESERVED_SLOTS = 500
#: The number of reserved slots in CLICK v4.  CLICK v4's editor lists no more range
#: addresses than this, whatever the formula says.
_V4_RESERVED_SLOTS = 5000
# The formula's length limit (``math_formula.MAX_INTERNAL_LENGTH``) allows at most 68
# operands, so the 500 operand slots are always enough.

# Pre-computed empty slot bytes: each slot is [2B tag LE][4B index LE][00 00].
# Avoids 1000 _variant_tagged_field() calls per Math instruction.
_SLOT_EMPTY_SIZE = 8
_EMPTY_OPERAND_BYTES = b"".join(
    struct.pack("<HI", _TAG_OPERAND, i) + b"\x00\x00" for i in range(_OPERAND_SLOTS)
)
_EMPTY_RESERVED_BYTES = b"".join(
    struct.pack("<HI", _TAG_RESERVED, i) + b"\x00\x00" for i in range(RESERVED_SLOTS)
)

#: The banks a Math result may be in, for each mode.  CLICK reports OBJ-004 for any other
#: bank.  A decimal result in SD must be one of ``WRITABLE_SD``, and CLICK reports OBJ-003
#: for any other SD.
RESULT_BANKS: dict[str, frozenset[str]] = {
    "decimal": frozenset({"DS", "DD", "DF", "TD", "CTD", "SD"}),
    "hex": frozenset({"DH", "YD"}),
}


def raw_formula_fields(blob: bytes) -> tuple[str, str, int] | None:
    """Return the stored formulas of a raw Math blob and its count of filled reserved slots.

    The result is ``(internal, display, filled reserved slots)``.  The internal formula is
    tag ``0x61FD``, and the display formula is tag ``0x6228``.  Each is ``""`` when the
    blob lacks it.  Return ``None`` when the blob's fields do not parse.
    """
    try:
        *_, fields = _decompose_blob(blob)
    except (ValueError, IndexError, struct.error):
        return None
    tags = {tag: value for tag, _, value in fields}
    listed = sum(1 for tag, _, value in fields if tag == _TAG_RESERVED and value)
    return tags.get(_TAG_FORMULA_INTERNAL, ""), tags.get(_TAG_FORMULA_DISPLAY, ""), listed


def range_interiors(expression: str) -> list[str]:
    """Return the addresses between the ends of each ``A : B`` range in a display formula."""
    return formula_range_interiors(expression.split())


def _reconstruct_expression(template_display: str, formula_internal: str) -> str:
    """Rebuild the formula from the display template and the internal formula's operands.

    CLICK stores the formula in two forms that this function uses:

    - ``template_display`` keeps the constants as the user typed them, but
      replaces each operand with an ``@`` placeholder.
    - ``formula_internal`` holds the operands, but rewrites the constants
      (for example ``200`` may become ``H200``).

    The function replaces each ``@`` with the next operand of the internal
    form.  The result keeps the constants as typed and shows no nicknames.
    If the template is missing, or its placeholders do not match the
    operands, the function returns the internal formula with spaces in
    place of ``#``.

    A blob from CLICK also has a display formula, which may show nicknames
    (for example ``<tag_name> + 200``).  The CSV form ignores it on purpose.
    If laddercodec adds an option to keep it, such as
    ``preserve_math_display``, that field is the one to read.
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


def _holds_nickname(expression: str) -> bool:
    """Return whether *expression* holds a ``<nickname>`` as CLICK's nickname view shows one."""
    return "<" in expression and ">" in expression.split("<", 1)[1]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Math(AfInstruction):
    """A math instruction.

    Attributes
    ----------
    expression:
        The formula in Click syntax (e.g. ``"DS65 + DS66"``).  Building a Math rewrites it
        in the form CLICK shows, with one space between tokens, uppercase function names
        and addresses in display form.  A formula that CLICK's Math dialog refuses raises
        :class:`FieldError`.  So does a ``<nickname>``, because Math takes only addresses.
    dest:
        Destination register (e.g. ``"DS67"``).
    mode:
        ``"decimal"`` or ``"hex"``.
    oneshot:
        Execute once on OFF→ON transition.
    """

    expression: str
    dest: str
    mode: Literal["decimal", "hex"] = "decimal"
    oneshot: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if self.mode not in RESULT_BANKS:
                check.refuse(
                    "mode",
                    f"{self.mode!r} is not 'decimal' or 'hex'",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            if _holds_nickname(self.expression):
                check.refuse(
                    "expression",
                    f"{self.expression!r} holds a <nickname>; Math takes addresses, not "
                    "nicknames (laddercodec cannot resolve a nickname to its address)",
                    Reason.ADDRESS,
                    code=Code.MATH_NICKNAME,
                )
            check.normalize("dest")
            # The banks allowed for the result, and how the formula is read, depend on the mode.
            if not check.refused("mode"):
                extra = HEX_MATH_RESULT if self.mode == "hex" else {}
                banks = RESULT_BANKS[self.mode]
                dest = check("dest", check_address, banks, bank_id="OBJ-004", **extra)
                if dest is not None:
                    # A result in SD must be a writable SD register.  CLICK reports OBJ-003
                    # for any other.
                    check.run(check_writable_sd, dest, check.field("dest"), click_id="OBJ-003")
                if not check.refused("expression"):
                    # Each refusal of the formula is recorded on the field Math.expression.
                    formula = check.run(parse, self.expression, self.mode)
                    if formula is not None:
                        self.expression = formula.display
            check.flag("oneshot")

    def to_csv(self) -> str:
        parts = [self.expression, self.dest]
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
        # A blob with 500 reserved slots pastes into CLICK v3 and v4.  Write v4's 5000 slots
        # only when the ranges have more than 500 addresses between their ends.
        interiors = formula.range_interiors
        reserved_slots = RESERVED_SLOTS if len(interiors) <= RESERVED_SLOTS else _V4_RESERVED_SLOTS
        interiors = interiors[:reserved_slots]
        out += struct.pack("<I", 9 + _OPERAND_SLOTS + reserved_slots + 1)

        # --- 9 header fields (standard sentinel) ---
        out += _tagged_field(_TAG_RESULT, self.dest)
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
        if reserved_slots == RESERVED_SLOTS:
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
    """Build a Math from tag data, or return None when laddercodec can't read it as one.

    The clipboard decoder and the program-file decoder both call it.
    """
    if class_name != "Math" or type_code != _MATH_TYPE_CODE:
        return None

    mode: Literal["decimal", "hex"] = "hex" if tag_flag(tags, 0x11FE) else "decimal"
    oneshot = tag_flag(tags, 0x11F8)

    # CLICK saves each address in the formula, and the result of a hex Math, as the user
    # typed it (ds1, DS001, XD0U, YD00).  read_as_typed() reads each into display form.
    # CLICK saves the result of a decimal Math in display form already.
    stored_dest = tag_value(tags, 0x6065)
    dest = read_as_typed(stored_dest) if mode == "hex" else stored_dest
    stored_internal = tag_value(tags, 0x61FD)
    internal = "#".join(read_as_typed(token) for token in stored_internal.split("#"))
    expression = _reconstruct_expression(
        tag_value(tags, 0x61FF),
        internal,
    ) or tag_value(tags, 0x6228)
    if not dest or not expression or _holds_nickname(expression):
        # In CLICK's nickname view, the display text shows nicknames, not addresses.
        # laddercodec can't read that text as a formula, so the blob stays raw.
        return None

    try:
        math = Math(
            expression=expression,
            dest=dest,
            mode=mode,
            oneshot=oneshot,
        )
    except FieldError:
        # The decoders build the Math in a mode that keeps most refusals on the instruction
        # (see laddercodec.operands.unchecked).  A refusal that no instruction can keep
        # still raises, and then the blob stays raw.
        return None
    if dest != stored_dest or internal != stored_internal:
        # The stored text differs from the fields.  Mark the Math so that encoding it
        # writes the bytes CLICK stored, with each address as the user typed it.
        read_in_another_form(math)
    # Older laddercodec wrote the H prefix only on a decimal constant, and a hex Math
    # refuses decimal constants.  So only a decimal Math is checked.
    findings = _legacy_findings(stored_internal) if mode == "decimal" else []
    if findings:
        math._legacy_findings = findings
    return math


def _legacy_findings(formula_internal: str) -> list[tuple[str, str, str]]:
    """Return a finding for each 16-bit (``H``) constant in a stored formula that overflows.

    An ``H`` constant overflows when its value is outside 16 bits.

    Older laddercodec wrote a decimal integer outside -32768..32767 as ``H70000``.  CLICK
    runs such a constant as its low 16 bits, read as a signed value.
    """
    found = []
    for token in formula_internal.split("#"):
        body = token[1:] if token.startswith("H") else ""
        digits = body[1:] if body.startswith("-") else body
        # Older laddercodec wrote at most 11 characters, the length of the longest integer
        # that CLICK prints (-2147483648).
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
        raise CsvError(f"math expects 2 positional args (expression, dest), got {len(call.args)}")

    expression, dest = call.args
    mode_arg = call.kwargs.get("mode", "decimal")
    if mode_arg == "decimal":
        mode: Literal["decimal", "hex"] = "decimal"
    elif mode_arg == "hex":
        mode = "hex"
    else:
        raise CsvError(f"math mode must be 'decimal' or 'hex', got {mode_arg!r}")

    return Math(
        expression=expression,
        dest=dest,
        mode=mode,
        oneshot=check_csv_flag(call.kwargs, "oneshot", "Math.oneshot"),
    )


SPEC = AfInstructionFamilySpec(
    family_name="math",
    instruction_types=(Math,),
    binary_class_names=("Math",),
    from_tags=from_tags,
    csv_names=("math",),
    parse_csv_call=parse_af_call,
)
