"""Convert a parsed CSV rung (``RungAst``) to ``Rung`` objects.

``convert_rung`` reads the circuit of a parsed CSV rung and lays it out the way CLICK's
syntax check draws it (``docs/internals/layout.md``).  Pin rows become the pin inputs of
the box, and the height of each box comes from ``cell_params()``.  The result is the same
whether the CSV holds the pad rows or leaves them out.  A rung that cannot be laid out
keeps the grid that ``convert_literal`` reads, as described below.

``convert_literal`` does this work:

- It converts condition, contact and compare tokens to model objects.
- It converts AF tokens (coils, timers, NOP).
- It folds each pin row (``.reset()``, ``.down()``, etc.) into the instruction it
  belongs to.  A pin row does not become a row of its own.
- It reads multi-row AF instructions.  A pinned box (``PinnedInstruction``: timers,
  counters, shift, drums) takes in its pin rows and its OR-leg rows.  Any other tall AF
  instruction keeps its blank-AF continuation rows as part of its block.
- It appends blank continuation rows to a tall AF instruction when the CSV leaves them
  out.

Pin rows
--------

Pin rows are continuation rows whose AF token starts with a dot
(``.reset()``, ``.down()``, etc.).  They represent secondary inputs to
the instruction on the row above:

    R, X001, -, ..., -, on_delay(T1,TD1,100,Tms)
    , X002, -, ..., -, .reset()

The ``.reset()`` row makes the timer retentive (``retained=True``).  The conditions and
wires on that row become the circuit that enables the reset.  The row does **not**
produce a separate AF instruction.

Blank-AF rows between the instruction and a pin are OR legs of the input above them.
They push every later input down, and ``pin_rows`` records where each input lands.  The
same rule applies to every pinned box.  Each instruction declares only its pins
(``pin_names()``), how the pins set its flags (``with_pins()``), and how many slots sit
above its main input (``lead_rows``, which is 1 for count_down).

Tall instructions
-----------------

Some AF instructions take up more than one grid row (timers 2, search and copy 2, send
and receive 3, and so on).  If the CSV leaves out their blank continuation rows, the
converter appends them, so that ``encode_rung()`` gets the correct ``logical_rows``.  If
a row inside the span of a tall box starts another AF instruction, the converter inserts
blank rows above that row.  This pushes it and every later row down.

After padding, the converter copies ``T`` and ``|`` wires down into the blank cells
below them.  This restores the vertical wires that the CSV writer leaves out when it
drops the padding rows.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Any, cast

from .._layout import LayoutError, drawn
from ..decode import Rung
from ..encode import AfToken, ConditionToken
from ..errors import CsvError
from ..instructions import (
    KNOWN_PIN_NAMES,
    CompareContact,
    Contact,
    Tee,
    parse_af_call,
)
from ..instructions import AfToken as RungAfToken
from ..instructions import ConditionToken as RungConditionToken
from ..model import (
    AfInstruction,
    ConditionInstruction,
    FieldError,
    PinnedInstruction,
    check_address,
)
from ..operands.unchecked import checked, refusals, unchecked
from .ast import (
    AfBlank,
    AfCall,
    AfNode,
    BlankCondition,
    ComparisonCondition,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
    HorizontalWire,
    JunctionDownWire,
    RowAst,
    RungAst,
    VerticalPassThroughWire,
)
from .location import AF_COLUMN, add_location, add_own_location, at, locate_held, located
from .token_parser import fill_blank_args, parse_af_token, parse_condition_token

# ---------------------------------------------------------------------------
# Condition / AF token conversion helpers
# ---------------------------------------------------------------------------

CONDITION_COLUMNS = 31


@dataclass
class _ParsedRow:
    """One CSV data row, converted to condition tokens, with the ``kind`` of its AF cell."""

    conditions: list[ConditionToken]
    kind: str
    token: AfToken = ""
    pin_name: str | None = None
    pin_args: tuple[str, ...] = ()
    #: The CSV line and rung row of the row, for an error's location.
    place: dict[str, int | None] = field(default_factory=dict)


@dataclass
class _ActiveBlock:
    """A multi-row AF block that is still gathering continuation rows."""

    token: AfInstruction
    main_conditions: list[ConditionToken]
    #: Rows of a pinned box's lead slots (above its main input), top first.
    lead_conditions: list[list[ConditionToken]] = field(default_factory=list)
    continuations: list[_ParsedRow] = field(default_factory=list)
    #: The CSV line and rung row of the instruction token's row, for an error's location.
    place: dict[str, int | None] = field(default_factory=dict)


def _blank_condition_row() -> list[ConditionToken]:
    """Return one all-blank condition row."""
    return [""] * CONDITION_COLUMNS


def _is_blank_row(conditions: Sequence[object]) -> bool:
    return all(c == "" for c in conditions)


def _unused_pin_blank_rows(gap: Sequence[Sequence[object]], unused: int) -> int:
    """Return how many blank rows at the end of *gap* stand for the rows of unused pins.

    *gap* holds the rows of a pinned box just before a used pin.  At most *unused* rows
    count.
    """
    count = 0
    while count < min(unused, len(gap)) and _is_blank_row(gap[-1 - count]):
        count += 1
    return count


def pinned_gap_height(gap: Sequence[Sequence[object]], unused: int) -> int:
    """Return the number of rows that a gap in the CSV of a pinned box lays out to.

    The gap is the rows between a used pin and the slot above it.  Those rows are OR legs
    of the slot above.  Each of the ``unused`` pins between the two takes a row below the
    legs, unless a blank row at the end of the gap already stands for it.  The CSV writer
    uses this to choose the rows that it writes.
    """
    return len(gap) + unused - _unused_pin_blank_rows(gap, unused)


def _af_visual_rows(token: AfToken) -> int:
    """Return the AF token's visual row count."""
    if isinstance(token, AfInstruction):
        return max(1, int(token.cell_params().get("visual_rows", 1)))
    return 1


def _hydrate_wire_continuations(condition_rows: list[list[ConditionToken]]) -> None:
    """Copy ``T`` and ``|`` wires down into the blank cells below them, in place.

    After the blocks are finished and padded, the padding rows are all blank.  This pass
    restores their vertical wires.  Where row *R* has a ``T`` (junction down), a ``|``
    (vertical pass-through) or a ``Tee`` (a contact with a wire down), a blank cell below
    it on row *R+1* becomes ``|``.

    The exception is a cell whose left neighbour ``(R+1, C-1)`` holds a horizontal path,
    which is anything other than ``""`` or ``"|"``.  That horizontal wire joins the end of
    the vertical wire above, so the vertical wire ends there and the cell stays blank.

    The pass works from top to bottom, so a vertical wire that spans several rows is
    copied all the way down.  It never writes the last row, because a vertical token
    there would point to a row that does not exist.
    """
    # Read rows 0 to N-3 and write rows 1 to N-2.  The last row, N-1, is never written.
    for row_idx in range(len(condition_rows) - 2):
        for col_idx in range(len(condition_rows[row_idx])):
            token = condition_rows[row_idx][col_idx]
            # A T or | wire, or a Tee, continues down into the cell below.
            propagates_down = isinstance(token, Tee) or token in ("T", "|")
            if propagates_down and condition_rows[row_idx + 1][col_idx] == "":
                # Check if a horizontal wire from the left already connects here.
                if col_idx > 0:
                    left = condition_rows[row_idx + 1][col_idx - 1]
                    if left not in ("", "|"):
                        continue  # the horizontal wire ends the vertical wire here
                condition_rows[row_idx + 1][col_idx] = cast(ConditionToken, "|")


def _parse_rung_row(row: RowAst, *, strict: bool) -> _ParsedRow:
    """Convert one parsed CSV row to condition tokens, and classify its AF cell."""
    conds: list[ConditionToken] = []
    try:
        for node in row.condition_nodes:
            conds.append(condition_node_to_token(node))
    except Exception as exc:
        add_location(exc, column=len(conds))  # the cell that failed
        raise
    for column, cond in enumerate(conds):
        locate_held([cond], column=column)
    af_node = row.af_node

    if isinstance(af_node, AfCall) and af_node.name.startswith("."):
        pin_name = af_node.name
        if pin_name not in KNOWN_PIN_NAMES:
            raise at(
                CsvError(
                    f"{pin_name}() is not a pin token. Write one of "
                    f"{', '.join(_pin_form(p) for p in sorted(KNOWN_PIN_NAMES))}."
                ),
                column=AF_COLUMN,
            )
        return _ParsedRow(
            conditions=conds,
            kind="pin",
            pin_name=pin_name,
            pin_args=af_node.args,
        )

    try:
        token = af_node_to_token(af_node, strict=strict)
    except Exception as exc:
        add_location(exc, column=AF_COLUMN)
        raise
    locate_held([token], column=AF_COLUMN)
    if token == "":
        return _ParsedRow(conditions=conds, kind="blank")
    if token == "NOP":
        return _ParsedRow(conditions=conds, kind="nop", token="NOP")

    if isinstance(token, PinnedInstruction) or _af_visual_rows(token) > 1:
        return _ParsedRow(conditions=conds, kind="block_main", token=token)
    return _ParsedRow(conditions=conds, kind="main", token=token)


def _flush_plain_rows(
    plain_rows: list[_ParsedRow],
    condition_rows: list[list[ConditionToken]],
    af_tokens: list[AfToken],
) -> None:
    """Move the buffered rows that belong to no block to *condition_rows* and *af_tokens*."""
    for row in plain_rows:
        condition_rows.append(row.conditions)
        af_tokens.append(row.token)
    plain_rows.clear()


def _start_active_block(
    row: _ParsedRow,
    *,
    lead_conditions: list[list[ConditionToken]] | None = None,
) -> _ActiveBlock:
    """Create a new active multi-row AF block from its main AF row."""
    if not isinstance(row.token, AfInstruction):
        raise AssertionError("block_main row must carry an AF instruction token")
    return _ActiveBlock(
        token=row.token,
        main_conditions=row.conditions,
        lead_conditions=lead_conditions or [],
        place=row.place,
    )


def _max_continuations(block: _ActiveBlock) -> int:
    """Return the most continuation rows that *block* can take in."""
    return max(0, _af_visual_rows(block.token) - 1)


def _call_name(token: AfInstruction) -> str:
    return f"{token.to_csv().split('(', 1)[0]}()"


def _pin_form(pin_name: str) -> str:
    """Return how a pin row writes *pin_name* in column AF, such as ``.reset()``."""
    return ".jump(DS1)" if pin_name == ".jump" else f"{pin_name}()"


def _consume_pinned_row(block: _ActiveBlock, row: _ParsedRow, token: PinnedInstruction) -> bool:
    """Take *row* into a pinned block if it belongs there, and return whether it did.

    The block takes its pin rows, in pin order, and the OR-leg rows between them.
    Nothing after the last pin belongs to the block, so legs under the last pin sit below
    the box.  The block takes blank rows after an earlier pin, or after the main input,
    even when no later pin follows.  ``_finalize_pinned_block`` returns the blank rows
    that fall below the box.

    A box with lead slots may put its main input on a NOP row right under the
    instruction token.  This is the bridge form of count_down.  The token row is then the
    lead row.
    """
    order = token.pin_names()
    if row.kind == "nop" and token.lead_rows:
        name = _call_name(token)
        if block.lead_conditions:
            raise CsvError(
                f"{name}: with NOP on the row under it, the {name} row is the box's unused "
                "Up row. The box has only one Up row, so the blank-AF row directly above it "
                f"can't be another. Leave no blank-AF row directly above {name}."
            )
        if block.continuations:
            raise CsvError(
                f"{name}: the row with NOP in column AF is the box's Down input. Put that "
                f"row directly under the {name} row."
            )
        block.lead_conditions = [block.main_conditions]
        block.main_conditions = row.conditions
        return True
    seen = [c.pin_name for c in block.continuations if c.kind == "pin"]
    if seen and seen[-1] == order[-1] and not (row.kind == "pin" and row.pin_name in order):
        return False
    if row.kind == "blank":
        block.continuations.append(row)
        return True
    if row.kind != "pin":
        return False
    pin_name = cast(str, row.pin_name)
    if pin_name not in order:
        pins = (
            f"Its only pin is {_pin_form(order[0])}."
            if len(order) == 1
            else f"Its pins are {', '.join(_pin_form(p) for p in order)}, in that order."
        )
        raise CsvError(f"{_call_name(token)} has no {pin_name}() pin. {pins}")
    remaining = order[order.index(seen[-1]) + 1 :] if seen else order
    if pin_name not in remaining:
        raise CsvError(
            f"Pin token {pin_name!r} is out of order or repeated for "
            f"{_call_name(token)}: pins go {', '.join(f'{p}()' for p in order)}"
        )
    block.continuations.append(row)
    return True


def _consume_active_row(block: _ActiveBlock, row: _ParsedRow) -> bool:
    """Consume a continuation row for the active block when it belongs there."""
    if isinstance(block.token, PinnedInstruction):
        return _consume_pinned_row(block, row, block.token)
    if len(block.continuations) >= _max_continuations(block):
        return False
    if row.kind == "blank":
        block.continuations.append(row)
        return True
    return False


def _finalize_pinned_block(
    block: _ActiveBlock,
) -> tuple[list[list[ConditionToken]], list[AfToken], list[_ParsedRow]]:
    """Lay out a pinned block, with each slot on its own row.

    Return the condition rows, the AF tokens and the tail.  The tail is the rows that the
    block took in that fall below the box.

    Lead slots come first, then the main input.  Rows between two slots are OR legs of
    the slot above.  An unused pin still takes a row of its own, below those legs.  CLICK
    lays out a leg added with Insert Row the same way: Reset on row 1, the leg on row 2,
    an unused Jump on row 3 and Jog on row 4.  Blank rows just above the next pin are read
    as the rows of the unused pins, not as legs.  Unused pins after the last used pin sit
    directly under it.  The box ends at the row of its last pin.
    """
    token = cast(PinnedInstruction, block.token)
    lead = token.lead_rows
    lead_rows = [_blank_condition_row() for _ in range(lead - len(block.lead_conditions))]
    rows = [*lead_rows, *block.lead_conditions, block.main_conditions]
    # The rows of every slot after the first.  With lead slots, the list starts with the
    # main input.
    slot_rows: list[int] = list(range(1, lead + 1))
    pins: dict[str, tuple[str, ...]] = {}
    pin_places: dict[str, dict[str, int | None]] = {}
    pending = list(block.continuations)
    prev = lead
    unused = 0
    for slot in token.pin_names():
        j = next((i for i, row in enumerate(pending) if row.kind == "pin"), None)
        if j is None or pending[j].pin_name != slot:
            unused += 1
            continue
        gap = [row.conditions for row in pending[:j]]
        rows.extend(gap)
        rows.extend(
            _blank_condition_row() for _ in range(pinned_gap_height(gap, unused) - len(gap))
        )
        slot_rows.extend(range(len(rows) - unused, len(rows)))
        prev = len(rows)
        rows.append(pending[j].conditions)
        slot_rows.append(prev)
        pins[slot] = pending[j].pin_args
        pin_places[slot] = pending[j].place
        pending = pending[j + 1 :]
        unused = 0
    slot_rows.extend(range(prev + 1, prev + 1 + unused))
    prev += unused

    height = prev + 1
    tail: list[_ParsedRow] = []
    for row in pending:
        if len(rows) < height:
            rows.append(row.conditions)
        else:
            tail.append(row)
    while len(rows) < height:
        rows.append(_blank_condition_row())

    slots = tuple(slot_rows)
    try:
        boxed = token.with_pins(pins, slots)
    except ValueError as exc:
        error = CsvError(str(exc), refusal=exc if isinstance(exc, FieldError) else None)
        if isinstance(exc, FieldError):
            # The box refuses a value that a pin row sets.  Locate the error at that row.
            culprit = _refused_pin(token, pins, slots)
            if culprit is not None:
                add_own_location(error, **pin_places[culprit], column=AF_COLUMN)
            _locate_at_pins(token, pins, slots, exc.errors, pin_places)
        raise error from exc
    # Inside ``read_csv(..., unchecked=True)``, the box keeps the refusals that ``with_pins``
    # would otherwise raise.  Locate each one where it would have been raised.
    _locate_at_pins(token, pins, slots, refusals(boxed), pin_places)
    locate_held([boxed], **block.place, column=AF_COLUMN)
    af_tokens: list[AfToken] = [boxed, *([""] * (len(rows) - 1))]
    if lead:
        af_tokens[lead] = "NOP"
    return rows, af_tokens, tail


def _locate_at_pins(
    token: PinnedInstruction,
    pins: dict[str, tuple[str, ...]],
    slot_rows: tuple[int, ...],
    found: Sequence[FieldError],
    pin_places: dict[str, dict[str, int | None]],
) -> None:
    """Locate each refusal in *found* that a value on a pin row causes at that pin's row."""
    for refusal in found:
        owner = _refusing_pin(token, pins, slot_rows, refusal)
        if owner is not None:
            add_own_location(refusal, **pin_places[owner], column=AF_COLUMN)


def _refusing_pin(
    token: PinnedInstruction,
    pins: dict[str, tuple[str, ...]],
    slot_rows: tuple[int, ...],
    refusal: FieldError,
) -> str | None:
    """Return the first used pin whose removal stops *refusal* from being raised, or None.

    The function builds the box again without each pin in turn.  Each build runs its
    checks inside ``checked()``, so it raises even inside ``read_csv(...,
    unchecked=True)``.  This way a refusal that the box would only hold there still shows
    which pin causes it.
    """
    for name in pins:
        try:
            with checked():
                token.with_pins({k: v for k, v in pins.items() if k != name}, slot_rows)
        except FieldError as other:
            if any(str(e) == str(refusal) for e in other.errors):
                continue
        except ValueError:
            continue
        return name
    return None


def _refused_pin(
    token: PinnedInstruction, pins: dict[str, tuple[str, ...]], slot_rows: tuple[int, ...]
) -> str | None:
    """Return the first used pin whose removal lets ``with_pins`` accept the box, or None.

    Either the row of that pin holds the refused value, such as a Drum's
    ``.jump(target)``, or the pin is itself the fault, such as a ``.reset()`` on a timer
    that can't be retentive.  Each build runs its checks, as in :func:`_refusing_pin`.
    """
    for name in pins:
        try:
            with checked():
                token.with_pins({k: v for k, v in pins.items() if k != name}, slot_rows)
        except ValueError:
            continue
        return name
    return None


def _finalize_generic_tall_block(
    block: _ActiveBlock,
) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand a non-pinned tall AF block to its full visual row span."""
    visual_rows = _af_visual_rows(block.token)
    condition_rows = [block.main_conditions]
    af_tokens: list[AfToken] = [block.token]

    for offset in range(visual_rows - 1):
        if offset < len(block.continuations):
            condition_rows.append(block.continuations[offset].conditions)
        else:
            condition_rows.append(_blank_condition_row())
        af_tokens.append("")

    return condition_rows, af_tokens


def _finalize_active_block(
    block: _ActiveBlock,
) -> tuple[list[list[ConditionToken]], list[AfToken], list[_ParsedRow]]:
    """Return the condition rows and AF tokens of *block*, and the rows that fall below it.

    Only a pinned block can have rows that fall below it.  An error is located at the cell
    of the instruction token.
    """
    with located(**block.place, column=AF_COLUMN):
        if isinstance(block.token, PinnedInstruction):
            return _finalize_pinned_block(block)
        rows, afs = _finalize_generic_tall_block(block)
        return rows, afs, []


def condition_node_to_token(node: object) -> ConditionToken:
    """Convert a parsed condition AST node to an encode-ready token.

    A contact read with a ``T:`` or ``|:`` prefix becomes a ``Tee`` around the contact.
    """
    if isinstance(node, (ContactCondition, EdgeCondition, ComparisonCondition)):
        contact = _contact_of(node)
        return Tee(contact) if node.wire_down else contact
    if isinstance(node, BlankCondition):
        return ""
    if isinstance(node, HorizontalWire):
        return "-"
    if isinstance(node, JunctionDownWire):
        return "T"
    if isinstance(node, VerticalPassThroughWire):
        return "|"
    if isinstance(node, GenericCondition):
        if re.fullmatch(r"[A-Za-z]{1,3}\d{1,5}", node.raw):
            check_address(node.raw, "Contact.operand")  # an address with digits not in 0-9
        raise CsvError(
            f"Could not read {node.raw!r} as a condition cell. Write a contact such as X001, "
            "~X001 or rise(X001), a compare such as DS1==1, or a wire: -, | or T."
        )
    raise TypeError(f"Unknown condition node type: {type(node).__name__}")


def _contact_of(
    node: ContactCondition | EdgeCondition | ComparisonCondition,
) -> ConditionInstruction:
    """Return the contact that a parsed contact, edge or compare node names, without its wire."""
    if isinstance(node, ContactCondition):
        return Contact(node.operand, kind="nc" if node.negated else "no", immediate=node.immediate)
    if isinstance(node, EdgeCondition):
        # An immediate edge contact is refused when it is built.
        return Contact(node.operand, kind=node.kind, immediate=node.immediate)
    return CompareContact(op=node.op, left=node.left, right=node.right)


def _af_call_to_token(call: AfCall, *, strict: bool = True) -> AfToken:
    """Convert a parsed AF call node to an encode-ready token.

    If the parser for the instruction accepts the token, the function returns what the
    parser built.  The parser refuses a token when it raises, or when it builds an
    instruction that holds refusals inside ``read_csv(..., unchecked=True)``.  If the
    parser refuses a token that holds a blank argument, the function reads the token
    again with the field of that argument left blank (:func:`_with_blank_fields`).  The
    result is the refusal that you get when you build the instruction with that field
    blank.  Its reason is ``missing``.  Inside ``read_csv(..., unchecked=True)``, the
    function returns the instruction, and the instruction keeps that refusal.
    """
    refused: ValueError | None = None
    try:
        token = parse_af_call(call)
    except ValueError as exc:
        refused, token = exc, None
    if refused is None:
        if token is None:
            if strict:
                raise CsvError(
                    f"Could not read {call.to_token()!r} as an instruction. Check its name "
                    "and its parentheses."
                )
            return ""
        if not refusals(token):
            return token
    blanked = _with_blank_fields(call)
    if blanked is not None:
        return blanked
    if refused is not None:
        raise refused
    return cast(AfInstruction, token)


def _with_blank_fields(call: AfCall) -> AfInstruction | None:
    """Return the instruction that *call* reads to with each blank argument's field blank.

    The function writes a marker into each blank argument and parses the token.  It tries
    each form in :data:`_MARKER_FORMS` in turn until the token parses: the marker alone,
    the marker in quotes (as a name), and the marker as a range (``M..M``, which fills two
    fields).  In the range form, a range with a blank end (``..``, ``..DS4``) also counts
    as a blank argument.  The fields that a marker lands in belong to that argument.

    The function then builds the instruction again from its fields, with each marker made
    blank, and runs the checks that construction runs.  Inside ``read_csv(...,
    unchecked=True)`` the instruction keeps the refusals.  Anywhere else the build raises
    them.

    Return None when the token holds no blank argument, when it does not parse with the
    markers, or when a marker lands in no field.
    """
    text = call.raw or call.to_token()
    for form, ranges in _MARKER_FORMS:
        found = _marked(text, form, ranges=ranges)
        if found is None:
            continue
        marked, marks = found
        try:
            with unchecked():
                probe = parse_af_call(cast(AfCall, parse_af_token(marked)))
        except ValueError:
            continue
        if probe is None:
            return None
        if all(_holds_text(probe, m) for m in marks):
            return cast(AfInstruction, _built_with_blanks(probe, marks))
    return None


#: The forms in which a blank argument is written to find its fields, and whether each
#: form is read as a range (:func:`fill_blank_args`).  ``@`` stands for the marker.
_MARKER_FORMS = (("@", False), ('"@"', False), ("@", True))


def _marked(text: str, form: str, *, ranges: bool) -> tuple[str, set[str]] | None:
    """Return *text* with a marker in *form* in each blank argument, and the markers.

    If *ranges* is true, each blank argument is read as a range.  Return None when no
    argument is blank.
    """
    marks: set[str] = set()

    def mark(i: int) -> str:
        found = f"BLANK{i}Q"  # not an address, a constant or a name
        while found in text:
            found += "Q"
        marks.add(found)
        return form.replace("@", found)

    marked = fill_blank_args(text, mark, ranges=ranges)
    return None if marked is None else (marked, marks)


def _holds_text(value: object, text: str) -> bool:
    """Return True if *value* is *text*, or holds *text* in an item or a dataclass field."""
    if is_dataclass(value) and not isinstance(value, type):
        return any(_holds_text(getattr(value, f.name), text) for f in fields(value))
    if isinstance(value, (list, tuple)):
        return any(_holds_text(item, text) for item in value)
    return value == text


def _built_with_blanks(value: object, marks: set[str]) -> object:
    """Return *value* with each field or item that is a marker in *marks* made blank.

    If *value* is a dataclass, the function builds it again, and each dataclass that it
    holds, so that each one runs its checks.
    """
    if is_dataclass(value) and not isinstance(value, type):
        changes = {
            f.name: _built_with_blanks(getattr(value, f.name), marks)
            for f in fields(value)
            if f.init
        }
        return replace(cast(Any, value), **changes)
    if type(value) in (list, tuple):
        return type(value)(_built_with_blanks(item, marks) for item in cast(Any, value))
    if isinstance(value, str) and value in marks:
        return ""
    return value


def af_node_to_token(node: AfNode, *, strict: bool = True) -> AfToken:
    """Convert a parsed AF AST node to an encode-ready token."""
    if isinstance(node, AfBlank):
        return ""
    if isinstance(node, AfCall):
        if node.name.upper() == "NOP":
            return "NOP"
        return _af_call_to_token(node, strict=strict)
    raise TypeError(f"Unknown AF node type: {type(node).__name__}")


def reads_back(token: object) -> bool:
    """Return True if the CSV token of *token*, with its pin rows, reads back equal to it.

    The function reads the token as ``read_csv(..., unchecked=True)`` reads it.  This way
    an instruction that holds refusals is compared with one that holds the same
    refusals.  If writing or reading the token fails, the function returns False, because
    the CSV cannot hold the instruction.
    """
    try:
        with unchecked():
            if isinstance(token, Tee) and isinstance(token.contact, ConditionInstruction):
                again: object = condition_node_to_token(parse_condition_token(token.to_csv()))
            elif isinstance(token, ConditionInstruction):
                again = condition_node_to_token(parse_condition_token(token.to_csv()))
            elif isinstance(token, AfInstruction):
                again = af_node_to_token(parse_af_token(token.to_csv()))
                if isinstance(token, PinnedInstruction) and isinstance(again, PinnedInstruction):
                    calls = [
                        cast(AfCall, parse_af_token(label))
                        for label in token.pin_labels()
                        if label is not None
                    ]
                    pins = {call.name: call.args for call in calls}
                    again = again.with_pins(pins, token.pin_rows)
            else:
                return False
    except Exception:  # noqa: BLE001 - a value the CSV can't hold breaks it anywhere
        return False
    return again == token


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_rung(rung: RungAst, *, strict: bool = True) -> list[Rung]:
    """Return the CLICK rungs that a CSV rung reads to, as CLICK's syntax check draws them.

    The circuit of the rung is read from its rows (:func:`convert_literal`) and laid out
    again (``docs/internals/layout.md``).  If CLICK would split the circuit, the rung comes
    back as several rungs, with the comment on the first.  A rung that cannot be laid out
    comes back as written.  That happens when it holds only wires and unwired NOPs, when
    the layout cannot draw it, or when ``laddercodec.check()`` reports a finding other
    than an unwired box input or a contact that feeds only a NOP.

    Raises
    ------
    CsvError
        If the rung contains unsupported constructs.  It is also raised, with the code
        ``layout-too-tall``, if a rung that would come back needs more than 32 rows.  The
        ``LayoutError`` is its ``__cause__``.
    """
    rung_line = rung.rows[0].line if rung.rows else None
    with located(rung_line=rung_line):
        literal = convert_literal(rung, strict=strict)
        try:
            rungs, _ = drawn(literal)
        except LayoutError as exc:
            raise CsvError(str(exc), code=exc.code) from exc
    for laid_out in rungs:
        locate_held(rung_tokens(laid_out), rung_line=rung_line)
    return rungs


def rung_tokens(rung: Rung) -> list[object]:
    """Return every cell token of *rung*, row by row, with the AF cell last in each row."""
    return [
        token
        for conditions, af in zip(rung.conditions, rung.instructions, strict=False)
        for token in (*conditions, af)
    ]


def convert_literal(rung: RungAst, *, strict: bool = True) -> Rung:
    """Return the grid of the rung as written, with pin rows on their slots and tall boxes
    padded to their height.

    Raises
    ------
    CsvError
        If the rung contains unsupported constructs.
    """
    if not rung.rows:
        raise CsvError("Rung has no rows")

    # --- Extract comment ---
    comment: str | None = None
    if rung.comment_rows:
        lines = [r.canonical.conditions[0] for r in rung.comment_rows]
        comment = "\n".join(lines)

    condition_rows: list[list[ConditionToken]] = []
    af_tokens: list[AfToken] = []
    plain_rows: list[_ParsedRow] = []
    active_block: _ActiveBlock | None = None

    for index, row in enumerate(rung.rows):
        place: dict[str, int | None] = {"line": row.line, "row": index}
        try:
            parsed = _parse_rung_row(row, strict=strict)
            parsed.place = place
            locate_held([*parsed.conditions, parsed.token], **place)

            if active_block is not None:
                try:
                    consumed = _consume_active_row(active_block, parsed)
                except Exception as exc:
                    add_location(exc, column=AF_COLUMN)
                    raise
                if consumed:
                    continue
                block_conditions, block_afs, tail = _finalize_active_block(active_block)
                condition_rows.extend(block_conditions)
                af_tokens.extend(block_afs)
                plain_rows.extend(tail)
                active_block = None

            if parsed.kind == "block_main":
                # Blank-AF rows just above a box with lead slots are those slots' rows.
                lead_conditions: list[list[ConditionToken]] = []
                if isinstance(parsed.token, PinnedInstruction):
                    while (
                        len(lead_conditions) < parsed.token.lead_rows
                        and plain_rows
                        and plain_rows[-1].kind == "blank"
                    ):
                        lead_conditions.insert(0, plain_rows.pop().conditions)
                _flush_plain_rows(plain_rows, condition_rows, af_tokens)
                active_block = _start_active_block(parsed, lead_conditions=lead_conditions)
                continue

            if parsed.kind == "pin":
                plain_rows.append(_ParsedRow(conditions=parsed.conditions, kind="blank"))
                continue

            plain_rows.append(parsed)
        except Exception as exc:
            add_location(exc, **place)
            raise

    if active_block is not None:
        block_conditions, block_afs, tail = _finalize_active_block(active_block)
        condition_rows.extend(block_conditions)
        af_tokens.extend(block_afs)
        plain_rows.extend(tail)

    _flush_plain_rows(plain_rows, condition_rows, af_tokens)

    # --- Auto-pad for tall instructions (any row, not just row 0) ---
    for i in range(len(af_tokens)):
        af_i = af_tokens[i]
        if isinstance(af_i, AfInstruction):
            needed = i + _af_visual_rows(af_i)
            while len(condition_rows) < needed:
                condition_rows.append(_blank_condition_row())
                af_tokens.append("")

    # --- Hydrate wire continuations ---
    _hydrate_wire_continuations(condition_rows)

    return Rung(
        cast(list[list[RungConditionToken]], condition_rows),
        cast(list[RungAfToken], af_tokens),
        comment,
    )
