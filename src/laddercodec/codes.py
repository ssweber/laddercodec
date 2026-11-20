"""Names for the rules behind refusals, ``check()`` findings and layout errors.

A :class:`~laddercodec.FieldError`, each refusal in its ``errors`` and a
:class:`~laddercodec.Finding` each have a ``code``.  The code is a
:class:`Code`, the kebab-case name of the rule.  CLICK's own id for the error is in
``click_id``, or ``None`` when CLICK has none.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["CLICK_IDS", "Code"]


class Code(StrEnum):
    """The name of the rule that a refusal, a finding or a layout error reports.

    Each member compares equal to its text: ``Code.NO_COIL == "no-coil"`` is true.  One code
    can come with several CLICK ids, or with none.  The ``click_id`` of the refusal, finding
    or layout error says which id CLICK gave.  The error codes page in the docs lists every
    code.
    """

    # Operand rules: these rules are the same in every instruction. ``field`` names the field.
    BLANK_FIELD = "blank-field"
    """A field that needs a value is blank."""
    NOT_AN_ADDRESS = "not-an-address"
    """Text that is no CLICK address or names no bank, or a value that is not text."""
    ADDRESS_OUT_OF_RANGE = "address-out-of-range"
    """A number outside its bank (``DS5000``, ``X017``)."""
    BANK_NOT_ALLOWED = "bank-not-allowed"
    """An address in a bank the field doesn't take."""
    UPPER_BYTE_NOT_ALLOWED = "upper-byte-not-allowed"
    """``XD0u`` or ``YD0u`` in a field that takes no upper byte."""
    NOT_CLICK_FORM = "not-click-form"
    """A stored value in a form that CLICK never writes. It is an address, a Math keypad name or a Math hex constant that is not in display form (``x1``, ``sqrt``), or a numeric tag that holds no number. A decoder keeps such a blob raw."""
    NOT_WRITABLE = "not-writable"
    """An address the instruction can't write: a read-only SC bit, an SD outside the writable list, or a Send to a read-only Modbus type."""
    POINTER_OUTSIDE_COPY = "pointer-outside-copy"
    """A pointer in any field but a single Copy's source or destination."""
    POINTER_BANK_NOT_ALLOWED = "pointer-bank-not-allowed"
    """A pointer to a bank the field's pointer can't address."""
    POINTER_NOT_DS = "pointer-not-ds"
    """A pointer whose index is no DS address."""
    CONSTANT_KIND_NOT_ALLOWED = "constant-kind-not-allowed"
    """A constant of a kind the field doesn't take, or a Python value of the wrong type, such as ``2.5`` for a Send or Receive ``quantity``."""
    NOT_A_CONSTANT = "not-a-constant"
    """Text read as neither an address nor a constant."""
    CONSTANT_OUT_OF_RANGE = "constant-out-of-range"
    """A constant outside the field's limits (its value, hex digits, float32, text length or typed length), or a minus sign where the field's lowest value is 0 or more."""
    INVALID_CONSTANT = "invalid-constant"
    """A constant in a form the field refuses: a ``+`` where no sign is taken, a sign before hex, a space in a count, a real with more significant digits than CLICK keeps, or a hex constant that spells a bank name (``DH``) in Compare's Data B opposite a hex Data A."""
    INVALID_CHAR_CODE = "invalid-char-code"
    """A ``$hh`` or a termination code that is no character code."""
    INVALID_TEXT_CONSTANT = "invalid-text-constant"
    """Quoted text holding a quote or a character CLICK doesn't keep."""
    NOT_A_FLAG = "not-a-flag"
    """A flag that is not True, False, 1 or 0."""
    INVALID_CHOICE = "invalid-choice"
    """Not one of the field's named values: a unit, type, op, format, kind, port, function code, stop or pattern cell."""

    # Shared rules: these rules apply to several instructions. ``invalid-subroutine-name`` and ``duplicate-subroutine-name`` apply to subroutine names in ``write_bundle`` and ``read_bundle``. For ``duplicate-subroutine-name``, ``write_bundle`` raises a ``CsvWriteError`` and ``read_bundle`` raises a ``CsvReadError``, and ``field`` is ``None``.
    OPTION_NOT_OFFERED = "option-not-offered"
    """A field or option CLICK's dialog greys out for the other fields' values."""
    RANGE_MIXED_BANKS = "range-mixed-banks"
    """A range whose two ends are in two banks."""
    RANGE_NOT_ASCENDING = "range-not-ascending"
    """A range that ends below its start, such as ``C5..C1``."""
    RANGE_CROSSES_SLOT = "range-crosses-slot"
    """An X or Y range that crosses a 16-point slot."""
    DUPLICATE_ADDRESS = "duplicate-address"
    """Two fields that must differ name one address, such as the two ends of the range ``C1..C1``."""
    TIMER_PAIR_MISMATCH = "timer-pair-mismatch"
    """A timer's or counter's done bit and accumulator with different numbers, such as ``T1`` with ``TD2``."""
    IMMEDIATE_CONTACT_NOT_X = "immediate-contact-not-x"
    """An immediate contact outside X."""
    IMMEDIATE_COIL_NOT_Y = "immediate-coil-not-y"
    """An immediate coil outside Y."""
    IMMEDIATE_EDGE_CONTACT = "immediate-edge-contact"
    """Immediate on a rise or fall contact."""
    IMMEDIATE_NOT_ALLOWED = "immediate-not-allowed"
    """Immediate on an instruction with no immediate form."""
    TEXT_ORDER_COMPARE = "text-order-compare"
    """``<`` or ``>`` on text, in a Compare or a Search."""
    INVALID_SUBROUTINE_NAME = "invalid-subroutine-name"
    """A subroutine name that is not text, is over 24 characters, holds a forbidden character or is a device name."""
    DUPLICATE_SUBROUTINE_NAME = "duplicate-subroutine-name"
    """Two subroutine names that are equal when the case of A-Z is ignored, such as ``Pump`` and ``pump``."""
    INVALID_INPUT_ROWS = "invalid-input-rows"
    """``pin_rows`` that is not one ascending row (1 to 255) per box input."""

    # Copy family: Copy, Block Copy, Fill, Pack and Unpack.
    COPY_BANK_INCOMPATIBLE = "copy-bank-incompatible"
    """A source bank or kind that can't copy into this destination bank."""
    CONSTANT_INTO_BIT = "constant-into-bit"
    """A single Copy of a constant into a bit address."""
    COPY_CONVERTER_BANK = "copy-converter-bank"
    """A converter the source and destination kinds don't offer."""
    COPY_TXT_NEEDS_CONVERT = "copy-txt-needs-convert"
    """A single Copy between TXT and a number, or a Block Copy from TXT into numbers, with no converter."""
    COPY_HEX_READS_AS_REAL = "copy-hex-reads-as-real"
    """A Copy source ``EH`` or ``1EH``. CLICK reads either one as a real."""
    TEXT_PAST_BANK = "text-past-bank"
    """Text a Copy writes that runs past TXT1000."""
    BLOCK_COPY_END_MISMATCH = "block-copy-end-mismatch"
    """A Block Copy ``dest_end`` that is not where the copy ends."""
    PACK_KIND_MISMATCH = "pack-kind-mismatch"
    """A Pack or Unpack kind (bits, words or text) that doesn't match the bank."""
    PACK_TOO_MANY = "pack-too-many"
    """A Pack source or Unpack destination past its count limit."""

    # Math: these rules apply to the formula of a Math instruction.
    MATH_NICKNAME = "math-nickname"
    """A formula that holds a ``<nickname>``."""
    MATH_INVALID_TOKEN = "math-invalid-token"
    """A word or character that is no formula part, or a formula that is not text."""
    MATH_CONSTANT_KIND = "math-constant-kind"
    """A hex constant in a decimal Math, a constant without an ``h`` in a hex Math, or a text constant in any Math."""
    MATH_CONSTANT_OUT_OF_RANGE = "math-constant-out-of-range"
    """Hex over 4 digits, a real past float32 or with more digits than CLICK keeps, an integer past int32, or leading zeros."""
    MATH_NESTING_DEPTH = "math-nesting-depth"
    """Parentheses more than 8 deep."""
    MATH_UNBALANCED_PARENS = "math-unbalanced-parens"
    """A ``)`` with no ``(``, or a ``(`` with no ``)``."""
    MATH_FUNCTION_MODE = "math-function-mode"
    """A function, an operator or ``PI`` that only the other mode's keypad has, such as ``SIN`` in a hex Math or ``XOR`` in a decimal Math."""
    MATH_SYNTAX_ERROR = "math-syntax-error"
    """A formula with tokens out of order, a comma outside a call, ``:`` outside a range function, or a wrong first or last token."""
    MATH_ARG_EXPRESSION = "math-arg-expression"
    """A function argument that is not one address or constant."""
    RANDOM_BOUND_TYPE = "random-bound-type"
    """A RAND bound that is a real, or in a bank RAND doesn't take."""
    RANDOM_EQUAL_BOUNDS = "random-equal-bounds"
    """RAND with equal bounds."""
    MATH_OPERAND_BANK = "math-operand-bank"
    """An address outside a ``SUM`` range, in a bank that the Math mode doesn't take. A decimal Math takes bit addresses only in a ``SUM`` range."""
    SUM_BANK_UNAVAILABLE = "sum-bank-unavailable"
    """SUM over a bank SUM doesn't read."""
    MATH_RANGE_MIXED_BANKS = "math-range-mixed-banks"
    """An ``a : b`` range in two banks."""
    MATH_RANGE_NOT_ASCENDING = "math-range-not-ascending"
    """An ``a : b`` range that runs high to low."""
    MEDIAN_RANGE_TOO_LARGE = "median-range-too-large"
    """MDN over more than 1024 bytes."""
    SUM_OPTION_SLOT = "sum-option-slot"
    """An X or Y SUM range with an end in the option slot."""
    MATH_FORMULA_TOO_LONG = "math-formula-too-long"
    """A formula longer than 270 characters in the internal form that CLICK stores."""

    # Other instructions: Compare, Search, Out variants, Drum, Send and Receive, For, and laddercodec's own types.
    COMPARE_MIXED_TYPES = "compare-mixed-types"
    """Compare operands in different groups (hex, numeric, text)."""
    SEARCH_VALUE_BANK = "search-value-bank"
    """A Search value whose kind or compare group doesn't search the table's bank."""
    COIL_TIME_UNIT = "coil-time-unit"
    """An Out variant with a time unit its kind lacks."""
    DEBOUNCE_NEEDS_PHASE = "debounce-needs-phase"
    """A debounce with neither phase filled."""
    DRUM_SIZE_OUT_OF_RANGE = "drum-size-out-of-range"
    """Drum steps or outputs outside 1 to 16."""
    DRUM_PATTERN_SHAPE = "drum-pattern-shape"
    """A drum pattern or event list that doesn't match its steps and outputs."""
    DRUM_STEP_EMPTY = "drum-step-empty"
    """A drum step with no event or duration."""
    FUNCTION_CODE_MISMATCH = "function-code-mismatch"
    """A Modbus function code that doesn't fit the remote type or the count."""
    COUNT_OUT_OF_RANGE = "count-out-of-range"
    """A Send or Receive count past its cap or room, or an odd TXT count."""
    TXT_START_NOT_ODD = "txt-start-not-odd"
    """A Send of TXT that starts at an even address, such as ``TXT1000``."""
    REMOTE_ADDRESS_OUT_OF_RANGE = "remote-address-out-of-range"
    """A remote start outside the MODBUS 984 ranges, or past FFFDh."""
    INVALID_MODBUS_TARGET = "invalid-modbus-target"
    """A Modbus target with a bad device_id, IP or port, or a Send or Receive target that is no Modbus target."""
    FOR_COUNT_BANK = "for-count-bank"
    """A For loop count in a bank the count doesn't take."""
    INVALID_TOKEN = "invalid-token"
    """A CSV token that doesn't follow its instruction's syntax."""
    INVALID_RAW = "invalid-raw"
    """A ``RawInstruction`` field with a value of the wrong type or out of range, or a ``raw(...)`` token whose ``rows=`` does not fit its ``pins=``."""
    INVALID_UNDECODED = "invalid-undecoded"
    """An ``Undecoded`` field refused."""
    INVALID_TEE = "invalid-tee"
    """A ``Tee`` built around something other than one contact."""
    INVALID_CIRCUIT = "invalid-circuit"
    """A ``Series``, ``Parallel``, ``Box``, ``Branch`` or ``Circuit`` built from a part it doesn't take, such as a Parallel with one leg, an empty Series outside a Parallel, or a pin that the box doesn't use."""

    # check() findings: ``check()`` reports these.
    NOT_SERIES_PARALLEL = "not-series-parallel"
    """A circuit that is not series-parallel."""
    NO_RAIL = "no-rail"
    """A contact whose input no rail reaches."""
    FEEDS_NO_BOX = "feeds-no-box"
    """A contact that feeds no box."""
    NO_COIL = "no-coil"
    """A path from the rail that reaches no box."""
    CONTACT_FEEDS_ONLY_NOP = "contact-feeds-only-nop"
    """A contact that feeds a NOP and no other box."""
    UNWIRED_INPUT = "unwired-input"
    """A box input (a Reset input, a Down input, ...) that no rail or contact reaches."""
    OUTPUT_ABOVE_BOX_INPUTS = "output-above-box-inputs"
    """A box above a lower box that uses an input row, such as a ``.reset()`` row, where the upper box's main input is on the lower box's main input circuit. That is the lower box's main input net, or a net that its main input circuit runs through from the rail. The rail reaches that net through a contact."""
    SHARED_INPUT_NET = "shared-input-net"
    """A box input whose net another input shares."""
    INPUT_WITHOUT_CONTACT = "input-without-contact"
    """A box input with no contact of its own."""
    INPUT_SHARES_ENABLE = "input-shares-enable"
    """A box input whose circuit shares contacts with an enable."""
    INPUTS_SHARE_CONTACTS = "inputs-share-contacts"
    """A box input whose circuit shares contacts with another box input."""
    UNPOWERED_BOX = "unpowered-box"
    """A box that no rail or contact reaches."""
    SHORTED_CONTACT = "shorted-contact"
    """A wire that joins a contact's two sides."""
    UNDECODED_RUNG = "undecoded-rung"
    """A rung that holds an ``Undecoded`` marker. The marker stands in for a rung that a decoder could not decode or that ``write_csv`` could not write."""

    # Layout: these codes come from laying a rung out. ``check()`` reports only ``layout-too-tall`` of them. ``lay_out()`` raises a ``LayoutError`` with one of these codes. When ``write_csv`` refuses a rung because of its layout, the ``__cause__`` of its ``CsvWriteError`` can be a ``LayoutError`` with one of these codes. For a rung that needs more than 32 rows, ``read_csv`` raises a ``CsvReadError`` and ``write_csv`` raises a ``CsvWriteError``, and the code of each is ``layout-too-tall``.
    LAYOUT_TOO_WIDE = "layout-too-wide"
    """A layout that needs more than 31 condition columns."""
    LAYOUT_TOO_TALL = "layout-too-tall"
    """A rung that needs more than the 32 rows that a CLICK rung holds."""
    LAYOUT_NOP_SPLIT = "layout-nop-split"
    """A rung that CLICK would split into several rungs, and that holds a NOP behind a contact or has only NOPs as outputs. laddercodec does not know how CLICK splits such a rung."""
    LAYOUT_CANNOT_DRAW = "layout-cannot-draw"
    """Nets that collide, cells that overlap, or a contact drawn twice."""


CLICK_IDS: dict[Code, tuple[str, ...]] = {
    Code.NOT_AN_ADDRESS: ("OBJ-002", "OBJ-003", "OBJ-004", "OBJ-005"),
    Code.ADDRESS_OUT_OF_RANGE: ("OBJ-002", "OBJ-003"),
    Code.BANK_NOT_ALLOWED: ("OBJ-003", "OBJ-004"),
    Code.NOT_WRITABLE: ("OBJ-003", "OBJ-004", "OBJ-018"),
    Code.POINTER_BANK_NOT_ALLOWED: ("OBJ-004",),
    Code.CONSTANT_OUT_OF_RANGE: ("OBJ-005", "OBJ-023"),
    Code.INVALID_CONSTANT: ("OBJ-005",),
    Code.INVALID_CHAR_CODE: ("OBJ-036",),
    Code.RANGE_MIXED_BANKS: ("OBJ-008",),
    Code.RANGE_NOT_ASCENDING: ("OBJ-009",),
    Code.RANGE_CROSSES_SLOT: ("OBJ-033", "OBJ-1009"),
    Code.DUPLICATE_ADDRESS: ("OBJ-012", "OBJ-014"),
    Code.INVALID_SUBROUTINE_NAME: ("GUI-040",),
    Code.DUPLICATE_SUBROUTINE_NAME: ("GUI-036",),
    Code.COPY_BANK_INCOMPATIBLE: ("OBJ-004", "OBJ-024"),
    Code.CONSTANT_INTO_BIT: ("OBJ-004", "OBJ-024"),
    Code.TEXT_PAST_BANK: ("OBJ-003",),
    Code.PACK_TOO_MANY: (
        "OBJ-003",
        "OBJ-027",
        "OBJ-032",
        "OBJ-039",
        "OBJ-040",
        "OBJ-041",
        "OBJ-042",
    ),  # fmt: skip
    Code.MATH_INVALID_TOKEN: ("OBJ-1001",),
    Code.MATH_CONSTANT_KIND: ("OBJ-1001",),
    Code.MATH_CONSTANT_OUT_OF_RANGE: ("OBJ-1009",),
    Code.MATH_NESTING_DEPTH: ("OBJ-1010",),
    Code.MATH_UNBALANCED_PARENS: ("OBJ-1004", "OBJ-1005"),
    Code.MATH_FUNCTION_MODE: ("OBJ-1006",),
    Code.MATH_SYNTAX_ERROR: ("OBJ-1001", "OBJ-037"),
    Code.MATH_ARG_EXPRESSION: ("OBJ-1001",),
    Code.RANDOM_BOUND_TYPE: ("OBJ-1001", "OBJ-1002"),
    Code.RANDOM_EQUAL_BOUNDS: ("OBJ-1001",),
    Code.MATH_OPERAND_BANK: ("OBJ-1002",),
    Code.SUM_BANK_UNAVAILABLE: ("OBJ-1002",),
    Code.MATH_RANGE_MIXED_BANKS: ("OBJ-1015",),
    Code.MATH_RANGE_NOT_ASCENDING: ("OBJ-1014",),
    Code.MEDIAN_RANGE_TOO_LARGE: ("OBJ-1013",),
    Code.MATH_FORMULA_TOO_LONG: ("OBJ-1008",),
    Code.DEBOUNCE_NEEDS_PHASE: ("OBJ-006",),
    Code.DRUM_STEP_EMPTY: ("OBJ-021", "OBJ-022", "OBJ-1019"),
    Code.FUNCTION_CODE_MISMATCH: ("OBJ-004",),
    Code.COUNT_OUT_OF_RANGE: ("OBJ-010", "OBJ-029"),
    Code.TXT_START_NOT_ODD: ("OBJ-028",),
    Code.REMOTE_ADDRESS_OUT_OF_RANGE: ("OBJ-010",),
    Code.FOR_COUNT_BANK: ("OBJ-004",),
    Code.COMPARE_MIXED_TYPES: ("OBJ-007",),
    Code.SEARCH_VALUE_BANK: ("OBJ-004",),
    Code.NOT_SERIES_PARALLEL: ("C0001",),
    Code.NO_RAIL: ("C0202",),
    Code.FEEDS_NO_BOX: ("C0202",),
    Code.NO_COIL: ("C0003",),
    Code.CONTACT_FEEDS_ONLY_NOP: ("C0003",),
    Code.UNWIRED_INPUT: ("C0202",),
    Code.OUTPUT_ABOVE_BOX_INPUTS: ("C000A",),
    Code.SHARED_INPUT_NET: ("C000A",),
    Code.INPUT_WITHOUT_CONTACT: ("C0205", "C0212"),
    Code.UNPOWERED_BOX: ("C0202",),
    Code.SHORTED_CONTACT: ("C0002",),
}
"""The CLICK ids that each code can come with.

A code that is missing here has no CLICK id.  A ``blank-field`` refusal has the id of the
check that refused the blank, whatever that id is.
"""
