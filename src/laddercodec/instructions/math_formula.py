"""The Math formula reader: one parse, and every form a Math blob stores printed from it.

The reader follows the check CLICK v4's Math dialog runs on OK.  Its steps and rules are
documented in ``docs/internals/instruction-blobs.md``, "Math formula grammar"; the step
numbers below are that section's.  :func:`parse` raises :class:`FieldError` on
``Math.expression``, naming the token and the rule, with every refusal it found in
:attr:`~FieldError.errors`:

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
7. :func:`_check_operands`: the banks each mode takes (:data:`_OPERANDS`), ranges, and
   then the 270-character cap of the internal template.

A refusal of the text's characters, a bracket, unbalanced or too deeply nested parentheses
and a token out of order each end the reading there.  Every other refusal is one of many:
each word refused, each constant's value, each key of the other mode, each address in a bank
its mode does not take and each range, and the reading goes on past it, taking a refused
word as what it looks like (an address, a constant, a function name).  After a word that
looks like none of those, the order is not checked, nor are the banks and ranges.  The
length is not checked after a refused constant or such a word, which have no internal form
to count.

:class:`Formula` holds the tokens; its properties print the display formula, the template,
the nickname display and the two internal ``#`` forms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

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
from ..operands.constants import INT16_MAX, INT16_MIN, fits_float32, hex_display
from ..operands.errors import Reason

_NAME = "Math.expression"


def _error(rule: str, reason: Reason, click_id: str | None = None) -> FieldError:
    """A refusal of the formula: ``Math.expression: rule``, ending with CLICK's id if known."""
    tail = f" ({click_id})" if click_id else ""
    return FieldError(f"{_NAME}: {rule}{tail}", field=_NAME, reason=reason, click_id=click_id)


def _raise(found: Sequence[FieldError]) -> NoReturn:
    """Raise the first refusal found, with :attr:`~FieldError.errors` holding them all."""
    first = found[0]
    first.errors = tuple(found)
    raise first


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
#: Every name on CLICK's Math keypads.
NAMES = FUNCTIONS | WORD_OPERATORS | {"PI"}
#: Keys only the decimal keypad has, and only the hex keypad.
DECIMAL_ONLY = TRIG | {"PI", "ABS", "^"}
HEX_ONLY = SHIFT | {"AND", "OR", "XOR"}

_SYMBOLS = frozenset("+-*/^(),:[]")
_SIGNS = ("+", "-")
_DIGITS = frozenset("0123456789")
_HEX_DIGITS = _DIGITS | frozenset("ABCDEFabcdef")

#: Parentheses nest at most 8 deep (OBJ-1010).
MAX_NESTING = 8
#: Most characters of the internal template, ``@`` per address and ``#`` between tokens
#: (OBJ-1008 "The Formula is too long"; a sum
#: of 68 addresses fits, 69 does not).
MAX_INTERNAL_LENGTH = 270
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1
#: The longest integer CLICK prints back: ``-2147483648``.
_MAX_PRINTED = 11
#: Registers of 2 and of 4 bytes, for the median's 1024-byte cap
#: (OBJ-1013).
_TWO_BYTE_BANKS = banks(Bank.DS | Bank.DH | Bank.TD | Bank.SD)
_FOUR_BYTE_BANKS = banks(Bank.DD | Bank.DF | Bank.CTD)
_MEDIAN_MAX_BYTES = 1024


@dataclass(frozen=True)
class _Operands:
    """The banks a formula of one mode takes; an address of any other is refused (OBJ-1002)."""

    #: Registers taken anywhere in the formula.
    anywhere: frozenset[str]
    #: Bits taken only as the range of ``SUM ( a : b )``.
    in_sum: frozenset[str]
    #: The rule, as each refusal states it.
    rule: str


#: The operand banks of each mode.  A decimal SUM takes no CT range on a CPU with the v4
#: functions; an older CPU's refusal of every bit is a project rule.
_OPERANDS = {
    "decimal": _Operands(
        banks(Bank.DS | Bank.DD | Bank.DF | Bank.TD | Bank.CTD | Bank.SD),
        banks(Bank.X | Bank.Y | Bank.C | Bank.T | Bank.SC),
        "a decimal Math takes only DS, DD, DF, TD, CTD and SD registers and decimal constants, "
        "and X, Y, C, T and SC bits only as the range of SUM ( a : b )",
    ),
    "hex": _Operands(
        banks(Bank.DH | Bank.XD | Bank.YD),
        frozenset(),
        "a hex Math takes only DH, XD and YD registers and hex constants",
    ),
}
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
    ``F1.5``, ``UH10``).  ``refused`` marks a word or constant already refused, read on as
    the ``kind`` it looks like.
    """

    kind: str
    text: str
    internal: str = ""
    refused: bool = False


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
            raise _error(
                f"{text!r} holds a text constant; a Math formula takes numbers only", Reason.KIND
            )
        if not _is_word_char(ch):
            raise _error(f"{ch!r} in {text!r} is no part of a Math formula", Reason.FORM)
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


def _word_refusal(word: str) -> FieldError:
    return _error(
        f"{word!r} is not an address, a function name or a constant; "
        "a Math formula takes only those",
        Reason.KIND,
        "OBJ-1001",
    )


def _classify(raws: Sequence[_Raw], i: int, mode: str, found: list[FieldError]) -> Token | None:
    """The token a raw word or symbol is (grammar steps 2 and 6), or a refusal (step 7).

    A refused word is added to ``found`` and comes back as the token it looks like, marked
    refused, or as ``None`` when it looks like no token.
    """
    raw = raws[i]
    word = raw.text

    def refuse(error: FieldError, kind: str | None, text: str = word) -> Token | None:
        found.append(error)
        return None if kind is None else Token(kind, text, refused=True)

    if raw.symbol:
        kind = "op" if word in "+-*/^" else word
        return Token(kind, word)
    if any(c.isdecimal() and not c.isascii() for c in word):
        return refuse(_error(f"{word!r} has a digit outside 0-9", Reason.FORM), None)
    hex_digits = _hex_digits(word)
    if raw.cut:
        if hex_digits is not None and mode == "hex":
            first, rest = word[: raw.cut], word[raw.cut :]
            error = _error(
                f"{word} is refused; CLICK reads the digits before E as a real number, so it "
                f"reads {word} as {first} then {rest}",
                Reason.FORM,
            )
            return refuse(error, "const")
        if hex_digits is None:
            return refuse(_word_refusal(word), None)
    upper = word.upper()
    if not raw.number and not raw.cut:
        if upper in NAMES:
            kind = "op" if upper in WORD_OPERATORS else "pi" if upper == "PI" else "func"
            try:
                return Token(kind, to_display(word, upper, _NAME))
            except FieldError as exc:
                return refuse(exc, kind, upper)
        try:
            address = normalize_address(word, _NAME)
        except FieldError as exc:
            # Only an address not in display form is refused here.
            return refuse(exc, "addr")
        if address_parts(address) is not None:
            try:
                check_address(address, _NAME, ADDRESS_BANKS)
            except FieldError as exc:
                return refuse(exc, "addr", address)
            return Token("addr", address)
    if hex_digits is not None:
        if mode == "decimal":
            error = _error(
                f"{hex_display(hex_digits)} is a hex constant; a decimal Math takes decimal "
                "constants such as 7",
                Reason.KIND,
                "OBJ-1001",
            )
            return refuse(error, "const")
        if len(hex_digits) > 4:
            # CLICK counts the digits as typed, leading zeros too (0FFFEh is refused).
            error = _error(
                f"{hex_digits}h is outside 0h..FFFFh; a hex constant has at most 4 digits",
                Reason.RANGE,
                "OBJ-1009",
            )
            return refuse(error, "const")
        try:
            text = to_display(word, hex_display(hex_digits), _NAME)
        except FieldError as exc:
            return refuse(exc, "const")
        return Token("const", text, f"UH{int(hex_digits, 16)}")
    if raw.number or (word and all(c in _DIGITS for c in word)):
        if mode == "hex":
            error = _error(
                f"{_signed(raws, i, word)} is a decimal constant; a hex Math takes hex "
                "constants such as 7h",
                Reason.KIND,
            )
            return refuse(error, "const")
        return Token("const", word)
    return refuse(_word_refusal(word), None)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def _check_parentheses(tokens: Sequence[Token], shown: str) -> FieldError | None:
    """The first refusal of the parentheses (grammar step 3), or ``None``."""
    depth = 0
    for token in tokens:
        if token.kind == "(":
            depth += 1
            if depth > MAX_NESTING:
                return _error(
                    f"{shown!r} nests parentheses {depth} deep; CLICK allows {MAX_NESTING}",
                    Reason.RANGE,
                    "OBJ-1010",
                )
        elif token.kind == ")":
            depth -= 1
            if depth < 0:
                return _error(f"{shown!r} has a ')' with no '('", Reason.FORM, "OBJ-1004")
    if depth > 0:
        return _error(f"{shown!r} has a '(' with no ')'", Reason.FORM, "OBJ-1005")
    return None


def _merge_signs(tokens: list[Token]) -> list[Token]:
    """Join a ``-`` or ``+`` and the decimal constant after it where a sign stands (step 5).

    Typed ``DS1 + ( +5 )`` is stored ``DS1#+#(#H+5#)``.
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
            # A refused constant joins its sign too, so the order reads as it would for 5.
            out.append(Token("const", f"{token.text}{nxt.text}", refused=nxt.refused))
            i += 2
            continue
        out.append(token)
        i += 1
    return out


def _decimal_internal(text: str) -> str | FieldError:
    """The internal form of a decimal constant, or the refusal of its value (OBJ-1009).

    CLICK reads an integer with ``_wtoi64``, keeps the low 32 bits, prints them with ``%d``
    and refuses the token when the printed length differs from the typed one, so
    ``3000000000``, ``007`` and ``-0`` are refused and ``6000000000``, whose low 32 bits
    print as ``1705032704``, passes; a typed ``+`` is put before the printed value
    (``+5``).  It stores an int16 value as ``H`` and a wider one as ``W``,
    keeping the typed text (``H+5``).  A real is stored as
    ``F`` and must fit float32.
    """
    body = text[1:] if text[:1] in _SIGNS else text
    if not all(c in _DIGITS for c in body):
        if not fits_float32(float(text)):
            return _error(
                f"{text} is outside the float32 range; a real constant fits 32 bits",
                Reason.RANGE,
                "OBJ-1009",
            )
        return f"F{text}"
    if len(text) > _MAX_PRINTED:
        # %d of a 32-bit value, with a typed '+', prints at most 11 characters.
        return _error(
            f"{text} is refused; CLICK prints an integer back in at most {_MAX_PRINTED} "
            "characters, which is not what was typed",
            _integer_reason(text, body),
            "OBJ-1009",
        )
    value = int(text)
    # _wtoi64 saturates at the int64 limits.
    low = (max(-(2**63), min(2**63 - 1, value)) + 2**31) % 2**32 - 2**31
    printed = f"+{low}" if text.startswith("+") else str(low)
    if len(printed) != len(text):
        if not _INT32_MIN <= value <= _INT32_MAX:
            return _error(
                f"{text} is outside {_INT32_MIN}..{_INT32_MAX}; an integer constant is 32-bit",
                _integer_reason(text, body),
                "OBJ-1009",
            )
        return _error(
            f"{text} is refused; CLICK reads it back as {printed}, which is not what was typed",
            Reason.FORM,
            "OBJ-1009",
        )
    return f"{'H' if INT16_MIN <= value <= INT16_MAX else 'W'}{text}"


def _integer_reason(text: str, body: str) -> Reason:
    """Why an integer CLICK refuses is refused: RANGE when its value is, else FORM.

    Leading zeros are a form: ``06000000000`` is refused where ``6000000000`` is taken, so
    the value counts only when it is refused without its zeros too.  ``body`` is ``text``
    without its sign.  The whole text is never read as a number, which Python refuses past
    4300 digits.
    """
    stripped = text[: len(text) - len(body)] + (body.lstrip("0") or "0")
    if len(stripped) > _MAX_PRINTED:
        return Reason.RANGE  # 11 digits and a sign, or 12 digits: no 32-bit value
    if stripped != text:
        alone = _decimal_internal(stripped)
        refused = isinstance(alone, FieldError) and alone.reason is Reason.RANGE
        return Reason.RANGE if refused else Reason.FORM
    return Reason.FORM if _INT32_MIN <= int(text) <= _INT32_MAX else Reason.RANGE


def _check_mode(tokens: Sequence[Token], mode: str, shown: str) -> list[FieldError]:
    """A refusal for each key of the other mode's keypad (grammar step 8).

    Each names ``Math.mode`` too: the key is taken in a Math of the other mode.
    """
    other = HEX_ONLY if mode == "decimal" else DECIMAL_ONLY
    other_mode = "hex" if mode == "decimal" else "decimal"
    return [
        FieldError(
            f"{_NAME}: {token.text} is {other_mode} only; {shown!r} is a {mode} Math (OBJ-1006)",
            field=(_NAME, "Math.mode"),
            reason=Reason.CONFLICT,
            click_id="OBJ-1006",
        )
        for token in tokens
        if token.kind in ("op", "func", "pi") and token.text in other
    ]


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
        # PI may be followed by '(': typed PI ( 2 ) is stored PI#(#H2#).
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


def _check_order(tokens: Sequence[Token]) -> FieldError | None:
    """The first refusal of the grammar checker (step 9), or ``None``.

    It reads token by token, each call form at its name.
    """
    call_separators: set[int] = set()
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None:
            reason = _follow_refusal(token, nxt)
            if reason:
                rule = f"{nxt.text!r} after {token.text!r}: {reason}"
                return _error(rule, Reason.FORM, "OBJ-1001")
        if token.kind == "," and i not in call_separators:
            # A comma outside RAND ( a , b ) or LSH..RRO ( a , b ) reads as a decimal comma
            # (OBJ-037: DS1 , DS2 and MAX ( DS1 , DS2 )
            # are refused).
            return _error(
                "',' stands outside RAND, LSH, RSH, LRO or RRO ( a , b ); CLICK reads it as a "
                "decimal comma: use a period (.) as the decimal point",
                Reason.FORM,
                "OBJ-037",
            )
        if token.kind == ":" and i not in call_separators:
            # A ':' outside SUM..AVG ( a : b ) is refused.
            return _error(
                "':' stands outside SUM, MAX, MIN, MDN or AVG ( a : b ); a range is written in "
                "one of those",
                Reason.FORM,
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
                return _error(
                    f"{token.text} takes {token.text} ( a , b ): a is {what}, b an address or a "
                    "constant, one each",
                    Reason.FORM,
                    "OBJ-1001",
                )
            call_separators.add(i + 3)
        elif token.text in RANGE_FUNCTIONS:
            # F ( a : b ), two addresses (SUM ( DS1 + DS2 )
            # is refused).
            shape = [t.kind for t in tokens[i + 1 : i + 6]]
            if shape != ["(", "addr", ":", "addr", ")"]:
                return _error(
                    f"{token.text} takes {token.text} ( a : b ), a range from address a to "
                    "address b",
                    Reason.FORM,
                )
            call_separators.add(i + 3)
        elif token.text in TRIG:
            # A ',' or ':' inside a trig call must be matched by a SUM.
            body = tokens[i + 1 : _closing(tokens, i + 1) + 1]
            balance = sum(t.kind in (",", ":") for t in body) - sum(t.text == "SUM" for t in body)
            if balance:
                return _error(
                    f"{token.text} ( ... ) holds a ',' or ':' that is not a SUM range; CLICK "
                    "refuses it",
                    Reason.FORM,
                    "OBJ-1001",
                )
    first, last = tokens[0], tokens[-1]
    if first.kind in (")", ",", ":") or (first.kind == "op" and first.text not in _SIGNS):
        return _error(f"the formula starts with {first.text!r}", Reason.FORM, "OBJ-1001")
    if last.kind not in (")", "pi", "const", "addr"):
        return _error(f"the formula ends with {last.text!r}", Reason.FORM, "OBJ-1001")
    return None


def _range_position(bank: str, number: str) -> int:
    if bank in _WORD_IO_BANKS:
        return _XY_WORD_ORDER.index(number) if number in _XY_WORD_ORDER else -1
    return int(number.rstrip("u"))


def _check_operands(tokens: Sequence[Token], mode: str) -> list[FieldError]:
    """Each address is in a bank its mode takes; a range stays in one bank and runs low : high.

    :data:`_OPERANDS` names the banks of each mode: the registers it takes anywhere, and the
    bits it takes only as the range of ``SUM ( a : b )``.  An address of any other bank is
    refused with OBJ-1002.  An X or Y range CLICK would store a wrong member list for is
    refused too.  One refusal for each address refused outside a SUM, one for each SUM
    refused, and at most one for each range; a refused address is not checked again.
    """
    operands = _OPERANDS[mode]
    texts = [t.text for t in tokens]
    found: list[FieldError] = []
    sum_at: dict[int, int] = {}  # each end of a SUM range: where its SUM stands
    for i in range(len(texts) - 5):
        if texts[i : i + 2] == ["SUM", "("] and texts[i + 3] == ":" and texts[i + 5] == ")":
            sum_at.update({i + 2: i, i + 4: i})
    sum_refused: set[int] = set()  # the SUMs refused for their bank, once each
    outside_sum: set[int] = set()  # the addresses refused for their bank, in a SUM or not
    for i, token in enumerate(tokens):
        parts = address_parts(token.text)
        if token.refused or parts is None:
            continue
        bank = parts[0]
        if bank in operands.anywhere or (i in sum_at and bank in operands.in_sum):
            continue
        outside_sum.add(i)
        if i not in sum_at:
            rule = f"{token.text} is refused; {operands.rule}"
            found.append(_error(rule, Reason.BANK, "OBJ-1002"))
        elif sum_at[i] not in sum_refused:
            sum_refused.add(sum_at[i])
            rule = f"SUM over {token.text} is refused; {operands.rule}"
            found.append(_error(rule, Reason.BANK, "OBJ-1002"))
    for i in range(1, len(texts) - 1):
        if texts[i] != ":" or tokens[i - 1].refused or tokens[i + 1].refused:
            continue
        low, high = address_parts(texts[i - 1]), address_parts(texts[i + 1])
        if low is None or high is None:
            continue
        shown = f"{texts[i - 1]} : {texts[i + 1]}"
        if low[0] != high[0]:
            found.append(
                _error(f"{shown} spans two banks; a range stays in one", Reason.FORM, "OBJ-1015")
            )
            continue
        count = _range_position(*high) - _range_position(*low) + 1
        if count < 1:
            rule = f"{shown} runs high to low; a range runs low : high"
            found.append(_error(rule, Reason.FORM, "OBJ-1014"))
            continue
        width = 2 if low[0] in _TWO_BYTE_BANKS else 4 if low[0] in _FOUR_BYTE_BANKS else 0
        if texts[i - 3 : i - 1] == ["MDN", "("] and width and count * width > _MEDIAN_MAX_BYTES:
            found.append(
                _error(
                    f"MDN ( {shown} ) covers {count * width} bytes; a median covers at most "
                    f"{_MEDIAN_MAX_BYTES}",
                    Reason.RANGE,
                    "OBJ-1013",
                )
            )
            continue
        # The member list matters only to a SUM: a bit range anywhere else is refused already.
        if low[0] in _XY_BANKS and i - 1 not in outside_sum:
            error = _check_xy_members(texts[i - 3], low[0], int(low[1]), int(high[1]))
            if error is not None:
                found.append(error)
    return found


def _check_xy_members(function: str, bank: str, start: int, end: int) -> FieldError | None:
    """The refusal of an X/Y range whose stored member list is not the points between its ends.

    CLICK v4 stores such a list for a range with an end in the option slot; the list is not
    what the range means, so laddercodec refuses the range.
    """
    listed = _xy_points_between(_xy_bound(start), _xy_bound(end))
    members = _xy_points_between(start, end)
    if listed == members:
        return None
    changes = []
    if left_out := [n for n in members if n not in listed]:
        changes.append(f"leave out {_xy_runs(bank, left_out)}")
    if added := [n for n in listed if n not in members]:
        changes.append(f"add {_xy_runs(bank, added)}")
    first, last = _OPTION_SLOT
    return _error(
        f"{function} ( {Address(bank, start).display} : {Address(bank, end).display} ) is "
        f"refused; CLICK v4 stores a wrong member list for a range with an end in "
        f"{Address(bank, first).display}-{Address(bank, last).display} "
        f"(it would {' and '.join(changes)})",
        Reason.RANGE,
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
    itself.  The rule is fitted for a C2-03CPU with no I/O modules.
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
        (``RAND ( 1 , 100 )`` is ``H1#RAND#H100#``).
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

    ``mode`` is ``"decimal"`` or ``"hex"``.  The error raised is the first refusal; its
    :attr:`~FieldError.errors` holds every refusal found (see the module docstring for
    where the reading stops).
    """
    raws = _lex(text)
    if not raws:
        # A Math blob with no formula decodes as raw(), so none is encoded.
        raise _error("is blank; a Math needs a formula", Reason.MISSING)
    for raw in raws:
        if raw.symbol and raw.text in ("[", "]"):
            # A pointer such as DS[DS1]: refused before its bank name reads as a word.
            raise _error(
                f"{raw.text!r} is part of a pointer; Math takes no pointer", Reason.POINTER
            )
    found: list[FieldError] = []
    tokens: list[Token] = []
    known = True  # every word looks like a token
    for i, raw in enumerate(raws):
        token = _classify(raws, i, mode, found)
        if token is None:
            known = False
            token = Token("word", raw.text, refused=True)
        tokens.append(token)
    shown = " ".join(t.text for t in tokens)
    if (error := _check_parentheses(tokens, shown)) is not None:
        _raise([*found, error])
    if mode == "decimal":
        tokens = _merge_signs(tokens)
        for k, t in enumerate(tokens):
            if t.kind != "const" or t.refused:
                continue
            internal = _decimal_internal(t.text)
            if isinstance(internal, FieldError):
                found.append(internal)
                tokens[k] = Token("const", t.text, refused=True)
            else:
                tokens[k] = Token("const", t.text, internal)
        shown = " ".join(t.text for t in tokens)
    found += _check_mode(tokens, mode, shown)
    if not known:
        _raise(found)
    if (error := _check_order(tokens)) is not None:
        _raise([*found, error])
    found += _check_operands(tokens, mode)
    formula = Formula(tuple(tokens))
    # The cap is on CLICK's internal template, which the blob stores as 0x6229.  At
    # 270 characters it holds at most 68 operands, so the 500 operand slots never overflow.
    # A refused constant, or a word that looks like no token, has no internal form to count;
    # a refused address is still an @ and a refused name its own text.
    uncounted = any(t.refused and t.kind in ("const", "word") for t in tokens)
    if not uncounted and (length := len(formula.internal(template=True))) > MAX_INTERNAL_LENGTH:
        found.append(
            _error(
                f"the formula is {length} characters in CLICK's internal form; CLICK allows "
                f"{MAX_INTERNAL_LENGTH}",
                Reason.RANGE,
                "OBJ-1008",
            )
        )
    if found:
        _raise(found)
    return formula
