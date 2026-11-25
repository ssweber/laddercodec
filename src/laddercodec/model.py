"""Shared domain types for ladder instructions.

Defines the ``InstructionType`` enum, the instruction base classes and the program
containers.  It re-exports:

- the field errors and :class:`Reason`, from :mod:`laddercodec.operands.errors`;
- the CLICK address check (:func:`check_address`), its display form
  (:func:`normalize_address`, :func:`normalize_fields`, :func:`normalize_items`) and the
  ``OPERAND_RE`` shape pattern, from :mod:`laddercodec.operands.address`;
- the flag check :func:`check_flag`, from :mod:`laddercodec.operands.checks`.

Every module in ``instructions/`` imports these types, so this module does not import
``instructions/`` when it loads.

The instruction dataclasses (Contact, Coil, …) and their func-code tables are in
:mod:`laddercodec.instructions`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

from .codes import Code
from .operands.address import ADDRESS_BANKS as ADDRESS_BANKS
from .operands.address import OPERAND_RE as OPERAND_RE
from .operands.address import XY_SLOTS as XY_SLOTS
from .operands.address import Address as Address
from .operands.address import _name_typed_text
from .operands.address import check_address as check_address
from .operands.address import display_form_only as display_form_only
from .operands.address import normalize_address as normalize_address
from .operands.address import normalize_fields as normalize_fields
from .operands.address import normalize_items as normalize_items
from .operands.address import to_display as to_display
from .operands.address import xy_slot as xy_slot
from .operands.checks import check_flag as check_flag
from .operands.errors import AddressError as AddressError
from .operands.errors import FieldError as FieldError
from .operands.errors import Reason as Reason
from .operands.message import make_refusal, operand, says, wrong_type
from .operands.unchecked import holds_refusals, rebuilt

if TYPE_CHECKING:
    from .decode import Rung
    from .instructions.undecoded import Undecoded

# ---------------------------------------------------------------------------
# Instruction base classes — used for isinstance dispatch
# ---------------------------------------------------------------------------


class Condition:
    """Base class for condition-side instructions (Contact, CompareContact).

    The constructor of each condition class in laddercodec accepts the keyword-only
    ``allow``, as :class:`Instruction` describes.
    """

    # Plain class attributes and not dataclass fields, so that they take no part in
    # equality. Instruction._legacy_findings and Instruction._refusal say what they hold.
    _legacy_findings: Collection[tuple[str, str, str]] = ()
    _refusal: FieldError | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _name_typed_text(cls)
        holds_refusals(cls)

    def to_csv(self) -> str:
        raise NotImplementedError

    def build_blob(self) -> bytes:
        raise NotImplementedError

    def cell_params(self) -> dict:
        raise NotImplementedError


class Instruction:
    """Base class for instructions in the AF (output) column, such as Coil, Timer and Copy.

    The constructor of each instruction class in laddercodec accepts the keyword-only
    ``allow``, a list of the codes of the refusals that you accept, such as
    ``Coil("X001", allow=["bank-not-allowed"])``. It builds an instruction whose refusals
    all have a listed code instead of raising, with the same limits as
    ``read_csv(path, allow=...)``. ``encode()`` writes that instruction from its fields.
    Any other refusal raises. The instruction does not store ``allow``. A bad ``allow``
    raises :class:`~laddercodec.LaddercodecError`.
    """

    # Keep this a plain class attribute. As a dataclass field in a subclass it would
    # take part in equality and change how decoded instructions compare.
    #: The ``(instruction, token, detail)`` findings that a decoder recorded when it read
    #: a form that an older laddercodec wrote. See :mod:`laddercodec.legacy`.
    _legacy_findings: Collection[tuple[str, str, str]] = ()
    #: The error that construction would have raised. An instruction built inside
    #: ``unchecked()`` from stored data keeps it here. See
    #: :mod:`laddercodec.operands.unchecked`. This is a plain class attribute for the
    #: same reason.
    _refusal: FieldError | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Wrap first, so that the error which holds_refusals keeps already names the typed text.
        _name_typed_text(cls)
        holds_refusals(cls)

    def to_csv(self) -> str:
        raise NotImplementedError

    def build_blob(self) -> bytes:
        raise NotImplementedError

    def cell_params(self) -> dict:
        raise NotImplementedError


class PinnedInstruction(Instruction):
    """An AF box with inputs ("slots") on several rows.

    The slots run from top to bottom. First come ``lead_rows`` slots above the main
    input, such as the Up input that count_down does not use. Next is the main input,
    which is the CSV row that holds the instruction token. Last comes one slot for each
    name in ``pin_names()``. ``pin_rows`` holds the row of every slot after the first.
    The blob stores these rows as its part bytes, and the box ends at the last of them.

    An OR leg under a slot pushes every later slot down. An OR leg under the last slot
    sits below the box. An unused pin still takes a row of its own. When ``lead_rows``
    is not zero, the AF cell of the main input's row holds a NOP in a decoded rung.
    """

    if TYPE_CHECKING:
        # Each pinned class defines pin_rows as a field of its frozen dataclass. A
        # read-only property here lets the type checker accept that field.
        @property
        def pin_rows(self) -> tuple[int, ...]: ...

    def _check_pin_rows(self) -> None:
        """Raise :class:`FieldError` unless ``pin_rows`` is valid for this box.

        Each pinned class calls this at the end of its ``__post_init__``.

        ``pin_rows`` needs one row for each slot after the first, in ascending order. That
        is ``lead_rows`` rows plus one for each pin name. The first slot is on row 0. The
        blob stores each row in one byte, so each row is 1 to 255.
        """
        name = f"{type(self).__name__}.pin_rows"
        rows = self.pin_rows
        want = self.lead_rows + len(self.pin_names())
        if not isinstance(rows, tuple) or len(rows) != want:
            raise make_refusal(
                FieldError,
                name,
                says(
                    "{rows} must be a tuple with one row per input ({want} for a {cls})",
                    rows=operand(rows),
                    want=want,
                    cls=type(self).__name__,
                ),
                field=name,
                reason=Reason.FORM,
                code=Code.INVALID_INPUT_ROWS,
            )
        if not all(type(row) is int and 1 <= row <= 255 for row in rows):
            raise make_refusal(
                FieldError,
                name,
                says("{rows} holds a row outside the whole numbers 1 to 255", rows=operand(rows)),
                field=name,
                reason=Reason.RANGE,
                code=Code.INVALID_INPUT_ROWS,
            )
        if any(later <= earlier for earlier, later in zip(rows, rows[1:], strict=False)):
            raise make_refusal(
                FieldError,
                name,
                says("{rows} must ascend", "each input sits below the last", rows=operand(rows)),
                field=name,
                reason=Reason.FORM,
                code=Code.INVALID_INPUT_ROWS,
            )

    @property
    def lead_rows(self) -> int:
        """The number of slots above the main input."""
        return 0

    def pin_names(self) -> tuple[str, ...]:
        """Return the CSV pin tokens below the main input, top first, such as ``.reset``."""
        raise NotImplementedError

    def pin_labels(self) -> tuple[str | None, ...]:
        """Return the CSV text of each pin row, with ``None`` for an unused pin."""
        raise NotImplementedError

    def with_pins(
        self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]
    ) -> PinnedInstruction:
        """Return a copy with its slots at ``pin_rows`` and the flags that ``pins`` sets.

        ``pins`` maps the name of each pin that the CSV uses to that pin's arguments.
        """
        raise NotImplementedError

    def with_pin_rows(self, pin_rows: tuple[int, ...]) -> PinnedInstruction:
        """Return a copy with its slots at ``pin_rows``. The copy keeps any refusals."""
        return rebuilt(cast(Any, self), pin_rows=pin_rows)


class InstructionType(IntEnum):
    """The low byte of each instruction type ID. The high byte is always 0x27."""

    CONTACT_NO = 0x11  # 0x2711
    CONTACT_NC = 0x12  # 0x2712
    CONTACT_EDGE = 0x13  # 0x2713 (rise/fall edge contacts)
    COMPARE = 0x14  # 0x2714 (comparison contacts: EQ/NE/GT/LT/GE/LE)
    COIL_OUT = 0x15  # 0x2715
    COIL_LATCH = 0x16  # 0x2716
    COIL_RESET = 0x17  # 0x2717
    TIMER = 0x18  # 0x2718 (on_delay / off_delay timers)
    COUNTER = 0x19  # 0x2719 (count_up / count_down counters)
    MATH = 0x1A  # 0x271A (math expression)
    DRUM = 0x1B  # 0x271B (event drum / time drum)
    SHIFT = 0x20  # 0x2720 (shift register)
    COPY = 0x21  # 0x2721 (single/block/fill/pack/unpack copy)
    SEARCH = 0x22  # 0x2722 (search table)
    CALL = 0x23  # 0x2723 (subroutine call)
    FOR_LOOP = 0x25  # 0x2725 (for loop)
    NEXT = 0x26  # 0x2726 (for loop terminator)
    RECEIVE = 0x28  # 0x2728 (modbus receive / read)
    SEND = 0x29  # 0x2729 (modbus send / write)


# Maps a stored 16-bit type code, such as 0x2711, to its InstructionType.
TYPE_CODE_TO_ITYPE: dict[int, InstructionType] = {
    0x2711: InstructionType.CONTACT_NO,
    0x2712: InstructionType.CONTACT_NC,
    0x2713: InstructionType.CONTACT_EDGE,
    0x2714: InstructionType.COMPARE,
    0x2715: InstructionType.COIL_OUT,
    0x2716: InstructionType.COIL_LATCH,
    0x2717: InstructionType.COIL_RESET,
    0x2718: InstructionType.TIMER,
}


# ---------------------------------------------------------------------------
# Program / Project containers
# ---------------------------------------------------------------------------


#: The longest subroutine or interrupt name. The name box in CLICK.exe's Add Subroutine
#: dialog accepts 24 characters.
PROGRAM_NAME_MAX = 24

#: The characters that CLICK.exe refuses in a program name, with GUI-040 "Invalid Program
#: Name".
_PROGRAM_NAME_FORBIDDEN = '\\/:*?"<>|'

#: The Windows device names that CLICK.exe refuses, with GUI-040, as the part of a
#: program name before its last dot. The list comes from a table in CLICK.exe. The
#: check ignores case.
_DEVICE_NAMES = frozenset(
    {"AUX", "CON", "NUL", "PRN", "CLOCK$"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)


def check_program_name(name: str, field_name: str) -> None:
    """Raise :class:`FieldError` naming ``field_name`` if CLICK refuses ``name`` for a subroutine.

    The check follows CLICK's Add New Subroutine dialog. It strips whitespace from both ends
    of the name and then refuses the name if:

    - it is blank;
    - it is longer than :data:`PROGRAM_NAME_MAX` characters;
    - it holds any of ``\\ / : * ? " < > |``;
    - the part before its last dot is a Windows device name (GUI-040).

    The check accepts ``Main``, ``.``, spaces inside the name, ``-`` and a leading digit.
    A name that is not text is refused as ``invalid-subroutine-name``.
    """
    if not isinstance(name, str):
        raise make_refusal(
            FieldError,
            field_name,
            wrong_type(name, "text"),
            field=field_name,
            reason=Reason.FORM,
            code=Code.INVALID_SUBROUTINE_NAME,
            then="Pass the name as a str.",
        )
    text = name.strip()
    if not text:
        raise make_refusal(
            FieldError,
            field_name,
            says("{name!r} is blank", "a subroutine needs a name", name=name),
            field=field_name,
            reason=Reason.MISSING,
            code=Code.BLANK_FIELD,
        )
    if len(text) > PROGRAM_NAME_MAX:
        raise make_refusal(
            FieldError,
            field_name,
            says(
                "{name!r} is {count} characters",
                "a subroutine name is at most {high}",
                name=name,
                count=len(text),
                high=PROGRAM_NAME_MAX,
            ),
            field=field_name,
            reason=Reason.RANGE,
            code=Code.INVALID_SUBROUTINE_NAME,
        )
    bad = sorted({ch for ch in text if ch in _PROGRAM_NAME_FORBIDDEN})
    if bad:
        raise make_refusal(
            FieldError,
            field_name,
            says(
                "{name!r} holds {bad}",
                "a subroutine name may not hold any of {forbidden}",
                name=name,
                bad=" ".join(bad),
                forbidden=" ".join(_PROGRAM_NAME_FORBIDDEN),
            ),
            field=field_name,
            reason=Reason.FORM,
            click_id="GUI-040",
            code=Code.INVALID_SUBROUTINE_NAME,
        )
    base = text.rsplit(".", 1)[0] if "." in text else text
    if base.upper() in _DEVICE_NAMES:
        raise make_refusal(
            FieldError,
            field_name,
            says(
                "{name!r} uses the Windows device name {base!r}",
                "CLICK refuses it as a subroutine name",
                name=name,
                base=base,
            ),
            field=field_name,
            reason=Reason.FORM,
            click_id="GUI-040",
            code=Code.INVALID_SUBROUTINE_NAME,
        )


@dataclass
class Program:
    """A single PLC program (main or subroutine) with its rungs.

    ``prog_idx`` is CLICK's program index: 1 for the main program, 2 and up for
    subroutines.
    """

    name: str
    prog_idx: int
    rungs: list[Rung] = field(default_factory=list)

    @property
    def undecoded(self) -> list[Undecoded]:
        """The undecoded markers in :attr:`rungs`, in rung order.

        The list is empty if every rung decoded.
        """
        from .undecoded import markers  # undecoded imports instructions, which import model

        return markers(self.rungs)


@dataclass
class Project:
    """A complete PLC project: main program plus subroutines."""

    main: Program
    subroutines: list[Program] = field(default_factory=list)
