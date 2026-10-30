"""RungAst → encode_rung() arguments converter.

Converts parsed CSV AST into the (logical_rows, condition_rows, af_tokens)
tuple consumed by ``encode_rung()``.  Handles:

- Condition/contact/compare token conversion to model objects
- AF token conversion (coils, timers, NOP)
- Pin continuation rows (``.reset()``, ``.down()``, etc.) — absorbed into
  the parent instruction rather than emitted as separate rows
- Multi-row AF instructions: pinned boxes (``PinnedInstruction``: timers,
  counters, shift, drums) absorb their pin and OR-leg rows; other tall AF
  instructions keep blank-AF continuation rows as part of the same block
- Auto-padding: tall AF instructions get blank continuation rows
  appended when the user omits them

Pin rows
--------

Pin rows are continuation rows whose AF token starts with a dot
(``.reset()``, ``.down()``, etc.).  They represent secondary inputs to
the instruction on the row above:

    R, X001, -, ..., -, on_delay(T1,TD1,100,Tms)
    , X002, -, ..., -, .reset()

The ``.reset()`` row makes the timer retentive (``retained=True``) and
contributes its conditions/wires as the reset-enable branch.  It does
**not** produce a separate AF instruction.

Blank-AF rows between the instruction and a pin are OR legs of the input
above them, and push every later input down (``pin_rows``).  This is one
rule for every pinned box; each instruction only declares its pins
(``pin_names()``), how they set its flags (``with_pins()``), and how many
slots sit above its main input (``lead_rows``, 1 for count_down).

Tall instructions
-----------------

Some AF instructions occupy more than one grid row visually (timers = 2,
search/copy = 2, send/receive = 3, etc.).  If the user CSV omits blank
continuation rows, they are auto-appended so ``encode_rung()`` receives
the correct ``logical_rows``.

After padding, a wire-continuation hydration pass propagates ``T`` and
``|`` tokens downward into blank cells, restoring vertical wire continuity
that was stripped by the writer's dehydration pass.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from ..encode import AfToken, ConditionToken
from ..instructions import (
    KNOWN_PIN_NAMES,
    CompareContact,
    Contact,
    parse_af_call,
)
from ..model import AfInstruction, InstructionType, PinnedInstruction
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

# ---------------------------------------------------------------------------
# Condition / AF token conversion helpers
# ---------------------------------------------------------------------------

CONDITION_COLUMNS = 31


@dataclass
class _ParsedRow:
    """One CSV data row converted into condition tokens plus AF classification."""

    conditions: list[ConditionToken]
    kind: str
    token: AfToken = ""
    pin_name: str | None = None
    pin_args: tuple[str, ...] = ()


@dataclass
class _ActiveBlock:
    """A multi-row AF block that is still gathering continuation rows."""

    token: AfInstruction
    main_conditions: list[ConditionToken]
    #: Rows of a pinned box's lead slots (above its main input), top first.
    lead_conditions: list[list[ConditionToken]] = field(default_factory=list)
    continuations: list[_ParsedRow] = field(default_factory=list)


def _blank_condition_row() -> list[ConditionToken]:
    """Return one all-blank condition row."""
    return cast(list[ConditionToken], [""] * CONDITION_COLUMNS)


def _is_blank_row(conditions: Sequence[object]) -> bool:
    return all(c == "" for c in conditions)


def _unused_pin_blank_rows(gap: Sequence[Sequence[object]], unused: int) -> int:
    """Blank rows at the end of a pre-pin gap that are read as unused pins' rows."""
    count = 0
    while count < min(unused, len(gap)) and _is_blank_row(gap[-1 - count]):
        count += 1
    return count


def pinned_gap_height(gap: Sequence[Sequence[object]], unused: int) -> int:
    """Rows a pinned box's CSV gap before a used pin lays out to.

    The gap's rows are OR legs of the slot above; each of the ``unused`` pins
    in between takes a row below them, unless a blank row at the gap's end
    already stands for it.  The writer uses this to pick the rows it emits.
    """
    return len(gap) + unused - _unused_pin_blank_rows(gap, unused)


def _af_visual_rows(token: AfToken) -> int:
    """Return the AF token's visual row count."""
    if isinstance(token, AfInstruction):
        return max(1, int(token.cell_params().get("visual_rows", 1)))
    return 1


def _hydrate_wire_continuations(condition_rows: list[list[ConditionToken]]) -> None:
    """Propagate ``T`` / ``|`` tokens downward into blank cells (in-place).

    After block finalization and auto-padding, padding rows are all-blank.
    This pass restores vertical wire continuity: wherever row *R* has a
    ``T`` (junction-down), ``|`` (vertical pass-through), or a condition
    instruction with ``wire_down=True``, row *R+1* gets a ``|`` if the
    cell is currently blank — unless a horizontal wire from the left
    already connects to that junction.

    A vertical wire terminates when ``(R+1, C-1)`` carries a horizontal
    path (anything other than ``""`` or ``"|"``), because the horizontal
    wire auto-snaps to the vertical endpoint above.

    Iterates top-to-bottom so multi-row vertical runs propagate correctly.
    Stops one row short of the last row — vertical tokens on the last row
    are invalid (they would point to a nonexistent row below).
    """
    # range(len - 2): iterate rows 0..N-3, writing to rows 1..N-2.
    # Row N-1 (last) is never written to.
    for row_idx in range(len(condition_rows) - 2):
        for col_idx in range(len(condition_rows[row_idx])):
            token = condition_rows[row_idx][col_idx]
            # A cell propagates | downward if it's a T/| wire token,
            # or a Contact/CompareContact with wire_down=True.
            propagates_down = token in ("T", "|") or (
                hasattr(token, "wire_down") and token.wire_down
            )
            if propagates_down and condition_rows[row_idx + 1][col_idx] == "":
                # Check if a horizontal wire from the left already connects here.
                if col_idx > 0:
                    left = condition_rows[row_idx + 1][col_idx - 1]
                    if left not in ("", "|"):
                        continue  # horizontal path snaps to vertical — no | needed
                condition_rows[row_idx + 1][col_idx] = cast(ConditionToken, "|")


def _parse_rung_row(row: RowAst, *, strict: bool) -> _ParsedRow:
    """Convert one parsed CSV row into tokens plus AF-row classification."""
    conds = [condition_node_to_token(n) for n in row.condition_nodes]
    af_node = row.af_node

    if isinstance(af_node, AfCall) and af_node.name.startswith("."):
        pin_name = af_node.name
        if pin_name not in KNOWN_PIN_NAMES:
            raise ConvertError(f"Unknown pin token: {pin_name!r}")
        return _ParsedRow(
            conditions=conds,
            kind="pin",
            pin_name=pin_name,
            pin_args=af_node.args,
        )

    token = af_node_to_token(af_node, strict=strict)
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
    """Append buffered non-block rows to the final decode-ready output."""
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
    )


def _max_continuations(block: _ActiveBlock) -> int:
    """Maximum number of continuation rows a block type can absorb."""
    return max(0, _af_visual_rows(block.token) - 1)


def _call_name(token: AfInstruction) -> str:
    return f"{token.to_csv().split('(', 1)[0]}()"


def _consume_pinned_row(block: _ActiveBlock, row: _ParsedRow, token: PinnedInstruction) -> bool:
    """Absorb pin rows (in pin order) and the leg rows between them.

    Nothing after the last pin belongs to the block: legs under it sit below
    the box.  Blank rows after an earlier pin (or the main input) are absorbed
    even when no later pin follows; ``_finalize_pinned_block`` hands back the
    ones past the box.

    A box with lead slots may put its main input on a NOP row right under the
    instruction token (count_down's bridge form); the token row is then the
    lead row.
    """
    order = token.pin_names()
    if row.kind == "nop" and token.lead_rows:
        if block.lead_conditions or block.continuations:
            raise ConvertError(
                f"{_call_name(token)} takes a NOP bridge row only directly under it, "
                "with no row above it"
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
        raise ConvertError(f"Pin token {pin_name!r} is not supported for {_call_name(token)}")
    remaining = order[order.index(seen[-1]) + 1 :] if seen else order
    if pin_name not in remaining:
        raise ConvertError(
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
    """Lay out a pinned block, placing each slot on its own row.

    Lead slots come first, then the main input.  Rows between two slots are
    OR legs of the slot above.  An unused pin still takes a row of its own,
    below those legs (as CLICK lays out a leg added with Insert Row: Reset 1,
    leg 2, unused Jump 3, Jog 4).  Blank rows just above the next pin are
    read as the unused pins' rows, not legs.  Unused pins after the last used
    one sit directly under it, and the box ends at the last pin's row;
    absorbed rows past it are returned as the tail.
    """
    token = cast(PinnedInstruction, block.token)
    lead = token.lead_rows
    lead_rows = [_blank_condition_row() for _ in range(lead - len(block.lead_conditions))]
    rows = [*lead_rows, *block.lead_conditions, block.main_conditions]
    # Every slot after the first: the main input when there are lead slots.
    slot_rows: list[int] = list(range(1, lead + 1))
    pins: dict[str, tuple[str, ...]] = {}
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

    try:
        token = token.with_pins(pins, tuple(slot_rows))
    except ValueError as exc:
        raise ConvertError(str(exc)) from exc
    af_tokens: list[AfToken] = [token, *([""] * (len(rows) - 1))]
    if lead:
        af_tokens[lead] = "NOP"
    return rows, af_tokens, tail


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
    """Expand the current active block into decode-ready rows/tokens.

    Also returns the absorbed rows that fall below the block (pinned blocks only).
    """
    if isinstance(block.token, PinnedInstruction):
        return _finalize_pinned_block(block)
    rows, afs = _finalize_generic_tall_block(block)
    return rows, afs, []


def condition_node_to_token(node: object) -> ConditionToken:
    """Convert a parsed condition AST node to an encode-ready token."""
    if isinstance(node, BlankCondition):
        return ""
    if isinstance(node, HorizontalWire):
        return "-"
    if isinstance(node, JunctionDownWire):
        return "T"
    if isinstance(node, VerticalPassThroughWire):
        return "|"
    if isinstance(node, ContactCondition):
        itype = InstructionType.CONTACT_NC if node.negated else InstructionType.CONTACT_NO
        return Contact(
            type=itype,
            operand=node.operand,
            immediate=node.immediate,
            wire_down=node.wire_down,
        )
    if isinstance(node, EdgeCondition):
        return Contact(
            type=InstructionType.CONTACT_EDGE,
            operand=node.operand,
            edge_kind=node.kind,
            wire_down=node.wire_down,
        )
    if isinstance(node, ComparisonCondition):
        return CompareContact(
            op=node.op, left=node.left, right=node.right, wire_down=node.wire_down
        )
    if isinstance(node, GenericCondition):
        raise ValueError(f"Cannot convert generic condition to encode token: {node.raw!r}")
    raise TypeError(f"Unknown condition node type: {type(node).__name__}")


def _af_call_to_token(call: AfCall, *, strict: bool = True) -> AfToken:
    """Convert a parsed AF call node to an encode-ready token."""
    token = parse_af_call(call)
    if token is not None:
        return token
    if strict:
        raise ValueError(f"Unsupported AF instruction: {call.name!r}")
    return ""


def af_node_to_token(node: AfNode, *, strict: bool = True) -> AfToken:
    """Convert a parsed AF AST node to an encode-ready token."""
    if isinstance(node, AfBlank):
        return ""
    if isinstance(node, AfCall):
        if node.name.upper() == "NOP":
            return "NOP"
        return _af_call_to_token(node, strict=strict)
    raise TypeError(f"Unknown AF node type: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ConvertError(ValueError):
    """Raised when a RungAst cannot be converted to encode arguments."""


def convert_rung(
    rung: RungAst,
    *,
    strict: bool = True,
) -> tuple[int, list[list[ConditionToken]], list[AfToken], str | None]:
    """Convert a ``RungAst`` to ``encode_rung()`` arguments.

    Returns ``(logical_rows, condition_rows, af_tokens, comment)``.

    Raises
    ------
    ConvertError
        If the rung contains unsupported constructs.
    """
    if not rung.rows:
        raise ConvertError("Rung has no rows")

    # --- Extract comment ---
    comment: str | None = None
    if rung.comment_rows:
        lines = [r.canonical.conditions[0] for r in rung.comment_rows]
        comment = "\n".join(lines)

    condition_rows: list[list[ConditionToken]] = []
    af_tokens: list[AfToken] = []
    plain_rows: list[_ParsedRow] = []
    active_block: _ActiveBlock | None = None

    for row in rung.rows:
        parsed = _parse_rung_row(row, strict=strict)

        if active_block is not None:
            if _consume_active_row(active_block, parsed):
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

    logical_rows = len(condition_rows)
    return logical_rows, condition_rows, af_tokens, comment
