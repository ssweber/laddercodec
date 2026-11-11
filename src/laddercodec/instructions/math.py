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
from ..model import ADDRESS_BANKS, AfInstruction, FieldError, check_address
from .copy import BIT_BANKS
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
# The formula's length cap (``_MAX_INTERNAL_LENGTH``) allows at most 68 operands, within
# the 500 slots.

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


# ---------------------------------------------------------------------------
# Field rules (CLICK v4.00 Help CL170 Math decimal, CL203 Math hex, OBJ-10xx)
# ---------------------------------------------------------------------------

#: Result banks per mode (Inst_Math.dll result masks at 0x100042e6 / 0x10005c54; OBJ-004).
RESULT_BANKS: dict[str, frozenset[str]] = {
    "decimal": frozenset({"DS", "DD", "DF", "TD", "CTD", "SD"}),
    "hex": frozenset({"DH", "YD"}),
}
#: Keys only the decimal keypad has (CL170), and only the hex keypad (CL203).
_DECIMAL_ONLY = frozenset(
    {
        "SIN",
        "COS",
        "TAN",
        "ASIN",
        "ACOS",
        "ATAN",
        "LOG",
        "LN",
        "SQRT",
        "RAD",
        "DEG",
        "PI",
        "ABS",
        "^",
    }
)
_HEX_ONLY = frozenset({"AND", "OR", "XOR", "LSH", "RSH", "LRO", "RRO"})
#: Parentheses nest at most 8 deep (CL170, OBJ-1010).
_MAX_NESTING = 8
#: Bytes per register (Help CL196 data types) for the median's 1024-byte cap (OBJ-1013).
_REGISTER_BYTES = {"DS": 2, "DH": 2, "TD": 2, "SD": 2, "DD": 4, "DF": 4, "CTD": 4}
_MEDIAN_MAX_BYTES = 1024
#: SUM over a range refuses only CT on a CPU with the v4 functions (Q-M8).
_SUM_REFUSED_BANKS = frozenset({"CT"})
#: Most characters of the internal template, ``@`` per address and ``#`` between tokens
#: (Inst_Math.dll 0x1000a5fd compares with 0x10e; OBJ-1008 "The Formula is too long").
_MAX_INTERNAL_LENGTH = 270
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1
_TOKEN_ADDRESS_RE = re.compile(r"([A-Z]{1,3})(\d+u?)")


def _token_address(token: str) -> tuple[str, str] | None:
    """``(bank, number)`` of a formula token that is an address, else ``None``."""
    m = _TOKEN_ADDRESS_RE.fullmatch(token)
    if m is None or m.group(1) not in ADDRESS_BANKS:
        return None
    return m.group(1), m.group(2)


def _range_position(bank: str, number: str) -> int:
    if bank in ("XD", "YD"):
        return _XY_WORD_ORDER.index(number) if number in _XY_WORD_ORDER else -1
    return int(number.rstrip("u"))


def _check_expression(expression: str, mode: str) -> None:
    """Refuse a formula CLICK's Math dialog refuses; the expression is already spaced."""
    tokens = _TOKEN_RE.findall(expression)
    name = "Math.expression"
    depth = 0
    for token in tokens:
        if token == "(":
            depth += 1
            if depth > _MAX_NESTING:
                raise FieldError(
                    f"{name}: {expression!r} nests parentheses {depth} deep; "
                    f"CLICK allows {_MAX_NESTING}"
                )
        elif token == ")":
            depth -= 1
            if depth < 0:
                raise FieldError(f"{name}: {expression!r} has a ')' with no '('")
        elif token in (_DECIMAL_ONLY if mode == "hex" else _HEX_ONLY):
            other = "decimal" if mode == "hex" else "hex"
            raise FieldError(f"{name}: {token} is {other} only; {expression!r} is a {mode} Math")
    if depth > 0:
        raise FieldError(f"{name}: {expression!r} has a '(' with no ')'")

    # SUM ( a : b ) is the one place a bit may stand, and not a CT bit (Inst_Math.dll SUM
    # handler 0x10011290, OBJ-1002; an older CPU's refusal of every bit is a project rule).
    bit_ok: set[int] = set()
    for i in range(len(tokens) - 5):
        if tokens[i : i + 2] == ["SUM", "("] and tokens[i + 3] == ":" and tokens[i + 5] == ")":
            bit_ok.update((i + 2, i + 4))
    for i, token in enumerate(tokens):
        address = _token_address(token)
        if address is None or address[0] not in BIT_BANKS:
            continue
        if i not in bit_ok:
            raise FieldError(f"{name}: {token} is a bit; a bit stands only in SUM over a bit range")
        if address[0] in _SUM_REFUSED_BANKS:
            raise FieldError(f"{name}: SUM over {token} is refused; SUM takes no CT range")
    # The spaced form keeps a sign on its constant (``( -5 )``).
    for token in expression.split(" "):
        if _CONSTANT_RE.fullmatch(token.removeprefix("-")):
            _check_constant(token, name, mode)

    for i in range(1, len(tokens) - 1):
        if tokens[i] != ":":
            continue
        low, high = _token_address(tokens[i - 1]), _token_address(tokens[i + 1])
        if low is None or high is None:
            continue
        text = f"{tokens[i - 1]} : {tokens[i + 1]}"
        if low[0] != high[0]:
            raise FieldError(f"{name}: {text} spans two banks; a range stays in one (OBJ-1015)")
        count = _range_position(*high) - _range_position(*low) + 1
        if count < 1:
            raise FieldError(f"{name}: {text} runs high to low; a range runs low : high")
        width = _REGISTER_BYTES.get(low[0])
        if tokens[i - 3 : i - 1] == ["MDN", "("] and width and count * width > _MEDIAN_MAX_BYTES:
            raise FieldError(
                f"{name}: MDN ( {text} ) covers {count * width} bytes; "
                f"a median covers at most {_MEDIAN_MAX_BYTES}"
            )

    # The cap is on CLICK's internal template, which the blob stores as 0x6229 (Q-M7).  At
    # 270 characters it holds at most 68 operands, so the 500 operand slots never overflow.
    length = len(_make_internal(_make_template(expression)))
    if length > _MAX_INTERNAL_LENGTH:
        raise FieldError(
            f"{name}: the formula is {length} characters in CLICK's internal form; "
            f"CLICK allows {_MAX_INTERNAL_LENGTH}"
        )


def _check_constant(token: str, name: str, mode: str) -> None:
    """Refuse a constant the Math dialog refuses (Inst_Math.dll 0x1000e940, OBJ-1009).

    Each mode checks its own constants.  In hex mode a hex constant has at most 4 digits and
    is at most FFFFh.  In decimal mode CLICK reads an integer with ``_wtoi64``, keeps the low
    32 bits, prints them with ``%d`` and refuses the token when the printed length differs
    from the typed one (0x1000ead1).  So ``3000000000``, ``007`` and ``-0`` are refused,
    while ``6000000000``, whose low 32 bits print as ``1705032704``, passes.
    """
    if mode == "hex":
        if token.endswith("h"):
            digits = token.lstrip("-")[:-1]
            if len(digits) > 4 or int(digits, 16) > 0xFFFF:
                raise FieldError(
                    f"{name}: {token} is outside 0h..FFFFh; a hex constant has at most 4 digits"
                )
        return
    if not re.fullmatch(r"-?\d+", token):
        return
    value = int(token)
    # _wtoi64 saturates at the int64 limits.
    low = (max(-(2**63), min(2**63 - 1, value)) + 2**31) % 2**32 - 2**31
    if len(str(low)) == len(token):
        return
    if not _INT32_MIN <= value <= _INT32_MAX:
        raise FieldError(
            f"{name}: {token} is outside {_INT32_MIN}..{_INT32_MAX}; an integer constant is 32-bit"
        )
    raise FieldError(
        f"{name}: {token} is refused; CLICK reads it back as {low}, which is not what was typed"
    )


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


#: Integer literals CLICK stores as a 16-bit constant (``H``); wider ones get ``W``.
_INT16_MIN, _INT16_MAX = -32768, 32767


def _internal_literal(token: str) -> str:
    if re.fullmatch(r"-?\d+", token):
        # v4_captures/sweep_math.bin: 32767 -> H, 40000 and 100000 -> W.
        prefix = "H" if _INT16_MIN <= int(token) <= _INT16_MAX else "W"
        return f"{prefix}{token}"
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
        if self.mode not in RESULT_BANKS:
            raise FieldError(f"Math.mode: {self.mode!r} is not 'decimal' or 'hex'")
        self.expression = _normalize_spacing(self.expression)
        check_address(self.result, "Math.result", RESULT_BANKS[self.mode])
        _check_expression(self.expression, self.mode)

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

    math = Math(
        expression=expression,
        result=result,
        mode=mode,
        oneshot=oneshot,
    )
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
        m = re.fullmatch(r"H(-?\d+)", token)
        if m and not _INT16_MIN <= int(m.group(1)) <= _INT16_MAX:
            low = int(m.group(1)) & 0xFFFF
            if low > _INT16_MAX:
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
