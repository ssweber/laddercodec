"""The Math formula reader: one parse, and every form a Math blob stores printed from it.

The reader follows the check CLICK v4's Math dialog runs on OK.  Its steps and rules are
documented in ``docs/internals/instruction-blobs.md``, "Math formula grammar"; the step
numbers below are that section's.  :func:`parse` raises :class:`FieldError` on
``Math.expression`` at the first refusal, naming the token and the rule:

1. :func:`_lex` splits the text as the dialog's tokenizer does (step 1): on spaces and
   tabs, on ``+ - * / ^ ( ) , :`` and on ``[ ]``.  A run of digits followed by ``.``,
   ``E`` or ``e`` is cut at the end of the longest real number it starts, so ``1.5E+10``
   is one token and the hex ``1Eh`` is ``1`` then ``Eh``; a run cut that way is refused.
2. :func:`_classify` names each word: a function or word operator, an address (which must
   pass the full address check), a constant of the Math's mode (step 6), or else a word,
   which is refused (step 7).
3. Parentheses balance and nest at most 8 deep (step 3).
4. In a decimal Math a ``-`` or ``+`` at the start, after ``(`` or after ``,`` joins the
   decimal constant after it (step 5); in a hex Math a sign stays its own token.
5. Each constant's value is checked (step 6), then the keys of the other mode's keypad are
   refused (step 8).
6. :func:`_check_order`: what may follow each token, the call forms, and how the formula
   starts and ends (step 9).
7. Bits, ranges and the 270-character cap of the internal template.

:class:`Formula` holds the tokens; its properties print the display formula, the template,
the nickname display and the two internal ``#`` forms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..model import (
    ADDRESS_BANKS,
    XY_SLOTS,
    Address,
    FieldError,
    check_address,
    normalize_address,
    to_display,
)
from ..operands.banks import Bank, banks
from ..operands.constants import INT16_MAX, INT16_MIN, fits_float32
from .copy import BIT_BANKS

_NAME = "Math.expression"

# ---------------------------------------------------------------------------
# Names (the keyword map of grammar step 2)
# ---------------------------------------------------------------------------

#: One-argument functions on the decimal keypad.
TRIG = frozenset({"SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN", "LOG", "LN", "SQRT", "RAD", "DEG"})
#: Functions over a range ``F ( a : b )``.
RANGE_FUNCTIONS = frozenset({"SUM", "MAX", "MIN", "MDN", "AVG"})
SHIFT = frozenset({"LSH", "RSH", "LRO", "RRO"})
#: Two-argument functions ``F ( a , b )``, stored infix as ``a#F#b``.
COMMA_FUNCTIONS = SHIFT | {"RAND"}
FUNCTIONS = TRIG | RANGE_FUNCTIONS | COMMA_FUNCTIONS | {"ABS"}
WORD_OPERATORS = frozenset({"MOD", "AND", "OR", "XOR"})
#: Every name on CLICK's Math keypads (Inst_Math.dll has no other names).
NAMES = FUNCTIONS | WORD_OPERATORS | {"PI"}
#: Keys only the decimal keypad has (CL170), and only the hex keypad (CL203).
DECIMAL_ONLY = TRIG | {"PI", "ABS", "^"}
HEX_ONLY = SHIFT | {"AND", "OR", "XOR"}

_SYMBOLS = frozenset("+-*/^(),:[]")
_SIGNS = ("+", "-")
_DIGITS = frozenset("0123456789")
_HEX_DIGITS = _DIGITS | frozenset("ABCDEFabcdef")

#: Parentheses nest at most 8 deep (CL170, OBJ-1010).
MAX_NESTING = 8
#: Most characters of the internal template, ``@`` per address and ``#`` between tokens
#: (Inst_Math.dll compares with 0x10e; OBJ-1008 "The Formula is too long"; Q-M7: a sum of
#: 68 addresses fits, 69 does not).
MAX_INTERNAL_LENGTH = 270
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1
#: The longest integer CLICK prints back: ``-2147483648``.
_MAX_PRINTED = 11
#: Registers of 2 and of 4 bytes (Help CL196 data types), for the median's 1024-byte cap
#: (OBJ-1013).
_TWO_BYTE_BANKS = banks(Bank.DS | Bank.DH | Bank.TD | Bank.SD)
_FOUR_BYTE_BANKS = banks(Bank.DD | Bank.DF | Bank.CTD)
_MEDIAN_MAX_BYTES = 1024
#: SUM over a range refuses only CT on a CPU with the v4 functions (Q-M8).
_SUM_REFUSED_BANKS = banks(Bank.CT)
_WORD_IO_BANKS = banks(Bank.XD | Bank.YD)
#: XD/YD addresses in order: ``MAX ( XD0 : XD3 )`` stores XD0u, XD1, XD2.
_XY_WORD_ORDER = ("0", "0u", "1", "2", "3", "4", "5", "6", "7", "8")
_XY_BANKS = banks(Bank.X | Bank.Y)
#: The CPU slot (1-16) and its option slot (21-36), and the 4 numbers between them (17-20).
_CPU_SLOT, _OPTION_SLOT = XY_SLOTS[0], XY_SLOTS[1]
_OPTION_GAP = _OPTION_SLOT[0] - _CPU_SLOT[1] - 1


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """One formula token.

    ``kind`` is ``(``, ``)``, ``,``, ``:``, ``op`` (``+ - * / ^`` and the word operators),
    ``func``, ``pi``, ``const`` or ``addr``.  ``text`` is the token as the display formula
    shows it; ``internal`` is a constant as the internal formula stores it (``H5``,
    ``F1.5``, ``UH10``).
    """

    kind: str
    text: str
    internal: str = ""


def address_parts(text: str) -> tuple[str, str] | None:
    """``(bank, number)`` of ``text`` in an address's shape, else ``None``.

    The shape is an uppercase bank of :data:`ADDRESS_BANKS`, digits 0-9, and ``u`` after
    XD or YD (``DS1``, ``X001``, ``XD0u``).  The number's range is not checked.
    """
    i = 0
    while i < len(text) and "A" <= text[i] <= "Z":
        i += 1
    bank, number = text[:i], text[i:]
    if bank not in ADDRESS_BANKS:
        return None
    digits = number[:-1] if bank in _WORD_IO_BANKS and number.endswith("u") else number
    if not digits or not all(c in _DIGITS for c in digits):
        return None
    return bank, number


def _hex_digits(word: str) -> str | None:
    """The digits of a hex constant, hex digits then one ``h`` or ``H``, else ``None``."""
    if len(word) < 2 or word[-1] not in "hH" or not all(c in _HEX_DIGITS for c in word[:-1]):
        return None
    return word[:-1]


def _hex_display(digits: str) -> str:
    """CLICK's form of a hex constant: uppercase digits without leading zeros, then ``h``."""
    return f"{digits.upper().lstrip('0') or '0'}h"


def _real_end(text: str, start: int) -> int:
    """End of the longest real number at ``start`` (``wcstod``'s reach), or ``start``.

    Digits with an optional ``.`` and fraction, or ``.`` and digits, then an optional
    exponent ``E``/``e``, a sign and digits.
    """
    n = len(text)
    i = start
    while i < n and text[i] in _DIGITS:
        i += 1
    digits = i - start
    if i < n and text[i] == ".":
        j = i + 1
        while j < n and text[j] in _DIGITS:
            j += 1
        digits += j - i - 1
        i = j
    if digits == 0:
        return start
    if i < n and text[i] in "Ee":
        j = i + 1
        if j < n and text[j] in _SIGNS:
            j += 1
        if j < n and text[j] in _DIGITS:
            while j < n and text[j] in _DIGITS:
                j += 1
            i = j
    return i


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in "._"


@dataclass(frozen=True)
class _Raw:
    """A token before classification: a symbol, a word, or a number the tokenizer cut."""

    text: str
    symbol: bool = False
    number: bool = False
    #: For a word the tokenizer cuts after a leading number: where the number ends.
    cut: int = 0


def _lex(text: str) -> list[_Raw]:
    """Split ``text`` as CLICK's tokenizer does (grammar step 1)."""
    out: list[_Raw] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        # Only a space or a tab separates tokens; other white space is refused below.
        if ch in " \t":
            i += 1
            continue
        if ch in _SYMBOLS:
            out.append(_Raw(ch, symbol=True))
            i += 1
            continue
        if ch in '"$':
            raise FieldError(
                f"{_NAME}: {text!r} holds a text constant; a Math formula takes numbers only"
            )
        if not _is_word_char(ch):
            raise FieldError(f"{_NAME}: {ch!r} in {text!r} is no part of a Math formula")
        end = i
        while end < n and _is_word_char(text[end]):
            end += 1
        # A run of digits (or none) then '.', 'E' or 'e' is read as a real number.
        k = i
        while k < end and text[k] in _DIGITS:
            k += 1
        if k < end and text[k] in ".Ee" and (k > i or text[k] == "."):
            stop = _real_end(text, i)
            if stop > i:
                if stop < n and _is_word_char(text[stop]):
                    # The word goes on past the number: CLICK cuts it in two.
                    end = stop
                    while end < n and _is_word_char(text[end]):
                        end += 1
                    out.append(_Raw(text[i:end], cut=stop - i))
                    i = end
                    continue
                out.append(_Raw(text[i:stop], number=True))
                i = stop
                continue
        out.append(_Raw(text[i:end]))
        i = end
    return out


def _signed(raws: Sequence[_Raw], i: int, word: str) -> str:
    """``word`` with the sign before it, where a sign stands (start, after ``(`` or ``,``)."""
    if i > 0 and raws[i - 1].text in _SIGNS and (i == 1 or raws[i - 2].text in ("(", ",")):
        return f"{raws[i - 1].text}{word}"
    return word


def _classify(raws: Sequence[_Raw], i: int, mode: str) -> Token:
    """The token a raw word or symbol is (grammar steps 2 and 6), or a refusal (step 7)."""
    raw = raws[i]
    word = raw.text
    if raw.symbol:
        kind = "op" if word in "+-*/^" else word
        return Token(kind, word)
    if any(c.isdecimal() and not c.isascii() for c in word):
        raise FieldError(f"{_NAME}: {word!r} has a digit outside 0-9")
    hex_digits = _hex_digits(word)
    if raw.cut:
        if hex_digits is not None and mode == "hex":
            first, rest = word[: raw.cut], word[raw.cut :]
            raise FieldError(
                f"{_NAME}: {word} is refused; CLICK reads the digits before E as a real "
                f"number, so it reads {word} as {first} then {rest}"
            )
        if hex_digits is None:
            raise FieldError(
                f"{_NAME}: {word!r} is not an address, a function name or a constant; "
                "a Math formula takes only those"
            )
    upper = word.upper()
    if not raw.number and not raw.cut:
        if upper in NAMES:
            text = to_display(word, upper)
            if upper in WORD_OPERATORS:
                return Token("op", text)
            return Token("pi" if upper == "PI" else "func", text)
        address = normalize_address(word)
        if address_parts(address) is not None:
            check_address(address, _NAME, ADDRESS_BANKS)
            return Token("addr", address)
    if hex_digits is not None:
        if mode == "decimal":
            raise FieldError(
                f"{_NAME}: {_hex_display(hex_digits)} is a hex constant; a decimal Math "
                "takes decimal constants such as 7"
            )
        if len(hex_digits) > 4:
            # CLICK counts the digits as typed, leading zeros too (0FFFEh is refused).
            raise FieldError(
                f"{_NAME}: {hex_digits}h is outside 0h..FFFFh; a hex constant has at most 4 digits"
            )
        return Token(
            "const", to_display(word, _hex_display(hex_digits)), f"UH{int(hex_digits, 16)}"
        )
    if raw.number or (word and all(c in _DIGITS for c in word)):
        if mode == "hex":
            raise FieldError(
                f"{_NAME}: {_signed(raws, i, word)} is a decimal constant; a hex Math takes "
                "hex constants such as 7h"
            )
        return Token("const", word)
    raise FieldError(
        f"{_NAME}: {word!r} is not an address, a function name or a constant; "
        "a Math formula takes only those"
    )


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def _check_parentheses(tokens: Sequence[Token], shown: str) -> None:
    depth = 0
    for token in tokens:
        if token.kind == "(":
            depth += 1
            if depth > MAX_NESTING:
                raise FieldError(
                    f"{_NAME}: {shown!r} nests parentheses {depth} deep; CLICK allows {MAX_NESTING}"
                )
        elif token.kind == ")":
            depth -= 1
            if depth < 0:
                raise FieldError(f"{_NAME}: {shown!r} has a ')' with no '('")
    if depth > 0:
        raise FieldError(f"{_NAME}: {shown!r} has a '(' with no ')'")


def _merge_signs(tokens: list[Token]) -> list[Token]:
    """Join a ``-`` or ``+`` and the decimal constant after it where a sign stands (step 5).

    Typed ``DS1 + ( +5 )`` is stored ``DS1#+#(#H+5#)`` (v4_captures/math_unary_plus_pi.bin).
    """
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if (
            token.text in _SIGNS
            and (not out or out[-1].kind in ("(", ","))
            and nxt is not None
            and nxt.kind == "const"
            and not nxt.internal
        ):
            out.append(Token("const", f"{token.text}{nxt.text}"))
            i += 2
            continue
        out.append(token)
        i += 1
    return out


def _decimal_internal(text: str) -> str:
    """The internal form of a decimal constant, or a refusal of its value (OBJ-1009).

    CLICK reads an integer with ``_wtoi64``, keeps the low 32 bits, prints them with ``%d``
    and refuses the token when the printed length differs from the typed one, so
    ``3000000000``, ``007`` and ``-0`` are refused and ``6000000000``, whose low 32 bits
    print as ``1705032704``, passes; a typed ``+`` is put before the printed value
    (``+5``).  It stores an int16 value as ``H`` and a wider one as ``W``
    (v4_captures/sweep_math.bin), keeping the typed text (``H+5``).  A real is stored as
    ``F`` and must fit float32.
    """
    body = text[1:] if text[:1] in _SIGNS else text
    if not all(c in _DIGITS for c in body):
        if not fits_float32(float(text)):
            raise FieldError(
                f"{_NAME}: {text} is outside the float32 range; a real constant fits 32 bits"
            )
        return f"F{text}"
    if len(text) > _MAX_PRINTED:
        # %d of a 32-bit value, with a typed '+', prints at most 11 characters.
        raise FieldError(
            f"{_NAME}: {text} is refused; CLICK prints an integer back in at most "
            f"{_MAX_PRINTED} characters, which is not what was typed"
        )
    value = int(text)
    # _wtoi64 saturates at the int64 limits.
    low = (max(-(2**63), min(2**63 - 1, value)) + 2**31) % 2**32 - 2**31
    printed = f"+{low}" if text.startswith("+") else str(low)
    if len(printed) != len(text):
        if not _INT32_MIN <= value <= _INT32_MAX:
            raise FieldError(
                f"{_NAME}: {text} is outside {_INT32_MIN}..{_INT32_MAX}; "
                "an integer constant is 32-bit"
            )
        raise FieldError(
            f"{_NAME}: {text} is refused; CLICK reads it back as {printed}, which is not what was "
            "typed"
        )
    return f"{'H' if INT16_MIN <= value <= INT16_MAX else 'W'}{text}"


def _check_mode(tokens: Sequence[Token], mode: str, shown: str) -> None:
    other = HEX_ONLY if mode == "decimal" else DECIMAL_ONLY
    for token in tokens:
        if token.kind in ("op", "func", "pi") and token.text in other:
            other_mode = "hex" if mode == "decimal" else "decimal"
            raise FieldError(
                f"{_NAME}: {token.text} is {other_mode} only; {shown!r} is a {mode} Math"
            )


_VALUES = ("func", "pi", "const", "addr")


def _follow_refusal(a: Token, b: Token) -> str | None:
    """Why ``b`` may not follow ``a`` (the follow table, grammar step 9), or ``None``."""
    if a.kind == "(":
        if b.kind == ")":
            return "the parentheses hold nothing"
        if b.kind in (",", ":") or (b.kind == "op" and b.text not in _SIGNS):
            return "it needs a value before it"
    elif a.kind == ")":
        if b.kind == "(" or b.kind in _VALUES:
            return "a value after ')' needs an operator between them"
    elif a.kind == "op":
        if b.kind == "op" and b.text in _SIGNS:
            return "a sign right after an operator is refused; put the signed value in parentheses"
        if b.kind in (")", ",", ":", "op"):
            return "an operator needs a value after it"
    elif a.kind in ("const", "addr", "pi"):
        # PI may be followed by '(': typed PI ( 2 ) is stored PI#(#H2#)
        # (v4_captures/math_unary_plus_pi.bin).
        if (b.kind == "(" and a.kind != "pi") or b.kind in _VALUES:
            return "two values need an operator between them"
        if a.kind == "pi" and b.kind in (",", ":"):
            return "PI may not stand before ',' or ':'"
    elif a.kind == "func":
        if b.kind != "(":
            return f"{a.text} takes its argument in parentheses, {a.text} ( ... )"
    elif a.kind in (",", ":"):
        if b.kind in (")", ",", ":", "op"):
            return "it needs a value after it"
        if b.kind == "func" and b.text in SHIFT:
            return f"{b.text} may not stand right after ',' or ':'"
    return None


def _closing(tokens: Sequence[Token], i: int) -> int:
    """Index of the ``)`` that closes the ``(`` at ``i``."""
    depth = 0
    for j in range(i, len(tokens)):
        if tokens[j].kind == "(":
            depth += 1
        elif tokens[j].kind == ")":
            depth -= 1
            if depth == 0:
                return j
    return len(tokens) - 1


def _check_order(tokens: Sequence[Token]) -> None:
    """The grammar checker (step 9), token by token, each call form at its name."""
    call_separators: set[int] = set()
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None:
            reason = _follow_refusal(token, nxt)
            if reason:
                raise FieldError(f"{_NAME}: {nxt.text!r} after {token.text!r}: {reason}")
        if token.kind == "," and i not in call_separators:
            # A comma outside RAND ( a , b ) or LSH..RRO ( a , b ) reads as a decimal comma
            # (OBJ-037; v4_captures/math_unary_plus_pi.bin: DS1 , DS2 and MAX ( DS1 , DS2 )
            # are refused).
            raise FieldError(
                f"{_NAME}: ',' stands outside RAND, LSH, RSH, LRO or RRO ( a , b ); "
                "CLICK reads it as a decimal comma: use a period (.) as the decimal point"
            )
        if token.kind == ":" and i not in call_separators:
            # A ':' outside SUM..AVG ( a : b ) is refused (BOB ruling: the colon helper was
            # not read past the comma case).
            raise FieldError(
                f"{_NAME}: ':' stands outside SUM, MAX, MIN, MDN or AVG ( a : b ); "
                "a range is written in one of those"
            )
        if token.kind != "func":
            continue
        if token.text in COMMA_FUNCTIONS:
            # F ( a , b ), one token per argument; LSH..RRO take an address first.
            first = ("addr",) if token.text in SHIFT else ("addr", "const")
            shape = tokens[i + 1 : i + 6]
            if not (
                len(shape) == 5
                and [t.kind for t in shape[::2]] == ["(", ",", ")"]
                and shape[1].kind in first
                and shape[3].kind in ("addr", "const")
            ):
                what = "an address" if token.text in SHIFT else "an address or a constant"
                raise FieldError(
                    f"{_NAME}: {token.text} takes {token.text} ( a , b ): a is {what}, "
                    "b an address or a constant, one each"
                )
            call_separators.add(i + 3)
        elif token.text in RANGE_FUNCTIONS:
            # F ( a : b ), two addresses (v4_captures/math_unary_plus_pi.bin:
            # SUM ( DS1 + DS2 ) is refused).
            shape = [t.kind for t in tokens[i + 1 : i + 6]]
            if shape != ["(", "addr", ":", "addr", ")"]:
                raise FieldError(
                    f"{_NAME}: {token.text} takes {token.text} ( a : b ), a range from "
                    "address a to address b"
                )
            call_separators.add(i + 3)
        elif token.text in TRIG:
            # A ',' or ':' inside a trig call must be matched by a SUM.
            body = tokens[i + 1 : _closing(tokens, i + 1) + 1]
            balance = sum(t.kind in (",", ":") for t in body) - sum(t.text == "SUM" for t in body)
            if balance:
                raise FieldError(
                    f"{_NAME}: {token.text} ( ... ) holds a ',' or ':' that is not a SUM range; "
                    "CLICK refuses it"
                )
    first, last = tokens[0], tokens[-1]
    if first.kind in (")", ",", ":") or (first.kind == "op" and first.text not in _SIGNS):
        raise FieldError(f"{_NAME}: the formula starts with {first.text!r}")
    if last.kind not in (")", "pi", "const", "addr"):
        raise FieldError(f"{_NAME}: the formula ends with {last.text!r}")


def _range_position(bank: str, number: str) -> int:
    if bank in _WORD_IO_BANKS:
        return _XY_WORD_ORDER.index(number) if number in _XY_WORD_ORDER else -1
    return int(number.rstrip("u"))


def _check_operands(texts: Sequence[str]) -> None:
    """Bits stand only in SUM over a bit range; a range stays in one bank and runs low : high.

    An X or Y range CLICK would store a wrong member list for is refused too.
    """
    # SUM ( a : b ) is the one place a bit may stand, and not a CT bit (Inst_Math.dll SUM
    # handler, OBJ-1002; an older CPU's refusal of every bit is a project rule).
    bit_ok: set[int] = set()
    for i in range(len(texts) - 5):
        if texts[i : i + 2] == ["SUM", "("] and texts[i + 3] == ":" and texts[i + 5] == ")":
            bit_ok.update((i + 2, i + 4))
    for i, text in enumerate(texts):
        parts = address_parts(text)
        if parts is None or parts[0] not in BIT_BANKS:
            continue
        if i not in bit_ok:
            raise FieldError(f"{_NAME}: {text} is a bit; a bit stands only in SUM over a bit range")
        if parts[0] in _SUM_REFUSED_BANKS:
            raise FieldError(f"{_NAME}: SUM over {text} is refused; SUM takes no CT range")
    for i in range(1, len(texts) - 1):
        if texts[i] != ":":
            continue
        low, high = address_parts(texts[i - 1]), address_parts(texts[i + 1])
        if low is None or high is None:
            continue
        shown = f"{texts[i - 1]} : {texts[i + 1]}"
        if low[0] != high[0]:
            raise FieldError(f"{_NAME}: {shown} spans two banks; a range stays in one (OBJ-1015)")
        count = _range_position(*high) - _range_position(*low) + 1
        if count < 1:
            raise FieldError(f"{_NAME}: {shown} runs high to low; a range runs low : high")
        width = 2 if low[0] in _TWO_BYTE_BANKS else 4 if low[0] in _FOUR_BYTE_BANKS else 0
        if texts[i - 3 : i - 1] == ["MDN", "("] and width and count * width > _MEDIAN_MAX_BYTES:
            raise FieldError(
                f"{_NAME}: MDN ( {shown} ) covers {count * width} bytes; "
                f"a median covers at most {_MEDIAN_MAX_BYTES}"
            )
        if low[0] in _XY_BANKS:
            _check_xy_members(texts[i - 3], low[0], int(low[1]), int(high[1]))


def _check_xy_members(function: str, bank: str, start: int, end: int) -> None:
    """Refuse an X/Y range whose stored member list is not the points between its ends.

    CLICK v4 stores such a list for a range with an end in the option slot (user ruling
    2026-11-12: the list is not what the range means, so laddercodec refuses the range).
    """
    listed = _xy_points_between(_xy_bound(start), _xy_bound(end))
    members = _xy_points_between(start, end)
    if listed == members:
        return
    changes = []
    if left_out := [n for n in members if n not in listed]:
        changes.append(f"leave out {_xy_runs(bank, left_out)}")
    if added := [n for n in listed if n not in members]:
        changes.append(f"add {_xy_runs(bank, added)}")
    first, last = _OPTION_SLOT
    raise FieldError(
        f"{_NAME}: {function} ( {Address(bank, start).display} : {Address(bank, end).display} ) "
        f"is refused; CLICK v4 stores a wrong member list for a range with an end in "
        f"{Address(bank, first).display}-{Address(bank, last).display} "
        f"(it would {' and '.join(changes)})"
    )


def _xy_points_between(low: int, high: int) -> list[int]:
    """The numbers of the X/Y points of :data:`XY_SLOTS` strictly between ``low`` and ``high``."""
    return [n for first, last in XY_SLOTS for n in range(first, last + 1) if low < n < high]


def _xy_runs(bank: str, numbers: list[int]) -> str:
    """``X032..X035`` for each run of consecutive numbers, runs joined with ``, ``."""
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return ", ".join(
        Address(bank, run[0]).display
        if len(run) == 1
        else f"{Address(bank, run[0]).display}..{Address(bank, run[-1]).display}"
        for run in runs
    )


def _xy_bound(number: int) -> int:
    """The bound an X/Y range end sets on the point numbers its range lists.

    An end's own number, but an end in the option slot counts as numbered right after the
    CPU slot (X021 is 17, X036 is 32).  So ``SUM ( X001 : X036 )`` lists the points
    numbered 2 to 31, X002..X016 and X021..X031, and ``SUM ( X021 : X116 )`` lists X021
    itself.  Fitted to the X and Y ranges of ``v4_captures/math_ranges_x_t.bin`` and
    ``math_ranges_xy_slots.bin`` (typed in CLICK v4, C2-03CPU, no I/O modules), not read
    from CLICK's code.
    """
    if _OPTION_SLOT[0] <= number <= _OPTION_SLOT[1]:
        return number - _OPTION_GAP
    return number


def range_interiors(texts: Sequence[str]) -> list[str]:
    """The addresses each ``A : B`` range of the display tokens lists, ranges in order.

    CLICK lists them in the reserved slots (tag ``0x688C``): the endpoints are ordinary
    operands, ``SUM ( DS201 : DS300 )`` stores DS202..DS299.  An X or Y range lists the
    points of :data:`XY_SLOTS` whose number lies between the bounds of its ends
    (:func:`_xy_bound`).
    """
    interiors: list[str] = []
    for i in range(1, len(texts) - 1):
        if texts[i] != ":":
            continue
        low, high = address_parts(texts[i - 1]), address_parts(texts[i + 1])
        if low is None or high is None or low[0] != high[0]:
            continue
        bank, start, end = low[0], low[1], high[1]
        if bank in _WORD_IO_BANKS:
            if start in _XY_WORD_ORDER and end in _XY_WORD_ORDER:
                inside = _XY_WORD_ORDER[_XY_WORD_ORDER.index(start) + 1 : _XY_WORD_ORDER.index(end)]
                interiors.extend(f"{bank}{n}" for n in inside)
            continue
        if bank in _XY_BANKS:
            listed = _xy_points_between(_xy_bound(int(start)), _xy_bound(int(end)))
            interiors.extend(Address(bank, n).display for n in listed)
            continue
        interiors.extend(Address(bank, n).display for n in range(int(start) + 1, int(end)))
    return interiors


# ---------------------------------------------------------------------------
# The parse and its printers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Formula:
    """A parsed Math formula; each property prints one of the forms a Math blob stores."""

    tokens: tuple[Token, ...]

    @property
    def display(self) -> str:
        """The formula as CLICK shows it (tag 0x6228), one space between tokens."""
        return " ".join(t.text for t in self.tokens)

    @property
    def template(self) -> str:
        """The display formula with ``@`` for each address (tag 0x61FF)."""
        return " ".join("@" if t.kind == "addr" else t.text for t in self.tokens)

    @property
    def nickname_display(self) -> str:
        """The display formula in nickname view: an address with no nickname is ``<?ADDR>``."""
        return " ".join(f"<?{t.text}>" if t.kind == "addr" else t.text for t in self.tokens)

    @property
    def operands(self) -> list[str]:
        """Each address, in order, duplicates kept: one operand slot each."""
        return [t.text for t in self.tokens if t.kind == "addr"]

    @property
    def range_interiors(self) -> list[str]:
        return range_interiors([t.text for t in self.tokens])

    def internal(self, *, template: bool = False) -> str:
        """The ``#`` form: the internal formula (tag 0x61FD) or template (tag 0x6229).

        Each token is written in its internal form (``200`` is ``H200``, ``Ah`` is
        ``UH10``) and the tokens are joined with ``#``.  ``F ( a , b )`` is written
        ``a#F#b`` and leaves an empty slot for its ``( , )``; a ``#`` follows each token
        but the last slot, so a formula that ends with one keeps a trailing ``#``
        (``RAND ( 1 , 100 )`` is ``H1#RAND#H100#``, typed in CLICK v4).
        """

        def form(token: Token) -> str:
            if token.kind == "addr":
                return "@" if template else token.text
            return token.internal or token.text

        parts: list[str] = []
        i = 0
        tokens = self.tokens
        while i < len(tokens):
            token = tokens[i]
            if token.kind == "func" and token.text in COMMA_FUNCTIONS:
                parts += [form(tokens[i + 2]), token.text, form(tokens[i + 4]), ""]
                i += 6
                continue
            parts.append(form(token))
            i += 1
        out = ""
        for k, part in enumerate(parts):
            if part:
                out += part if k == len(parts) - 1 else f"{part}#"
        return out


def parse(text: str, mode: str) -> Formula:
    """Read a Math formula as CLICK's Math dialog does; raise :class:`FieldError` if it refuses.

    ``mode`` is ``"decimal"`` or ``"hex"``.
    """
    raws = _lex(text)
    if not raws:
        # A Math blob with no formula decodes as raw(), so none is encoded.
        raise FieldError(f"{_NAME}: the formula is empty; a Math needs a formula")
    for raw in raws:
        if raw.symbol and raw.text in ("[", "]"):
            # A pointer such as DS[DS1]: refused before its bank name reads as a word.
            raise FieldError(f"{_NAME}: {raw.text!r} is part of a pointer; Math takes no pointer")
    tokens = [_classify(raws, i, mode) for i in range(len(raws))]
    shown = " ".join(t.text for t in tokens)
    _check_parentheses(tokens, shown)
    if mode == "decimal":
        tokens = _merge_signs(tokens)
        tokens = [
            Token("const", t.text, _decimal_internal(t.text)) if t.kind == "const" else t
            for t in tokens
        ]
        shown = " ".join(t.text for t in tokens)
    _check_mode(tokens, mode, shown)
    _check_order(tokens)
    _check_operands([t.text for t in tokens])
    formula = Formula(tuple(tokens))
    # The cap is on CLICK's internal template, which the blob stores as 0x6229 (Q-M7).  At
    # 270 characters it holds at most 68 operands, so the 500 operand slots never overflow.
    length = len(formula.internal(template=True))
    if length > MAX_INTERNAL_LENGTH:
        raise FieldError(
            f"{_NAME}: the formula is {length} characters in CLICK's internal form; "
            f"CLICK allows {MAX_INTERNAL_LENGTH}"
        )
    return formula
