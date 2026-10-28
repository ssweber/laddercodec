"""RungAst → encode_rung() arguments converter.

Converts parsed CSV AST into the (logical_rows, condition_rows, af_tokens)
tuple consumed by ``encode_rung()``.  Handles:

- Condition/contact/compare token conversion to model objects
- AF token conversion (coils, timers, NOP)
- Pin continuation rows (``.reset()``, ``.down()``, etc.) — absorbed into
  the parent instruction rather than emitted as separate rows
- Multi-row AF instructions: pinned families (timers, counters, shift,
  drum) absorb their continuation rows; other tall AF instructions keep
  blank-AF continuation rows as part of the same visual block
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

from dataclasses import dataclass, field, replace
from typing import cast

from ..encode import AfToken, ConditionToken
from ..instructions import (
    KNOWN_PIN_NAMES,
    CompareContact,
    Contact,
    Counter,
    Drum,
    Shift,
    Timer,
    get_af_family_for_token,
    parse_af_call,
)
from ..model import AfInstruction, InstructionType
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
# Pin row table — dot-prefixed AF tokens and their effects
# ---------------------------------------------------------------------------

#: Pin names that make the parent timer retentive.
_RETENTIVE_PINS = frozenset({".reset"})


# ---------------------------------------------------------------------------
# Condition / AF token conversion helpers
# ---------------------------------------------------------------------------

CONDITION_COLUMNS = 31
_PINNED_BLOCK_FAMILIES = frozenset({"timer", "counter", "shift", "drum"})


@dataclass
class _ParsedRow:
    """One CSV data row converted into condition tokens plus AF classification."""

    conditions: list[ConditionToken]
    kind: str
    token: AfToken = ""
    family_name: str | None = None
    pin_name: str | None = None
    pin_args: tuple[str, ...] = ()


@dataclass
class _ActiveBlock:
    """A multi-row AF block that is still gathering continuation rows."""

    family_name: str | None
    token: AfInstruction
    main_conditions: list[ConditionToken]
    leading_blank_conditions: list[ConditionToken] | None = None
    continuations: list[_ParsedRow] = field(default_factory=list)


def _blank_condition_row() -> list[ConditionToken]:
    """Return one all-blank condition row."""
    return cast(list[ConditionToken], [""] * CONDITION_COLUMNS)


def _is_blank_row(conditions: list[ConditionToken]) -> bool:
    return all(c == "" for c in conditions)


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

    family = get_af_family_for_token(token)
    visual_rows = _af_visual_rows(token)
    if family is not None and (family.family_name in _PINNED_BLOCK_FAMILIES or visual_rows > 1):
        return _ParsedRow(
            conditions=conds,
            kind="block_main",
            token=token,
            family_name=family.family_name,
        )
    if visual_rows > 1:
        return _ParsedRow(
            conditions=conds,
            kind="block_main",
            token=token,
        )
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
    leading_blank_conditions: list[ConditionToken] | None = None,
) -> _ActiveBlock:
    """Create a new active multi-row AF block from its main AF row."""
    if not isinstance(row.token, AfInstruction):
        raise AssertionError("block_main row must carry an AF instruction token")
    return _ActiveBlock(
        family_name=row.family_name,
        token=row.token,
        main_conditions=row.conditions,
        leading_blank_conditions=leading_blank_conditions,
    )


def _max_continuations(block: _ActiveBlock) -> int:
    """Maximum number of continuation rows a block type can absorb."""
    return max(0, _af_visual_rows(block.token) - 1)


def _pin_order(token: AfInstruction) -> tuple[str, ...] | None:
    """Pins of an instruction whose OR legs can push its later pins down, in order."""
    if isinstance(token, Drum):
        return (".reset", ".jump", ".jog")
    if isinstance(token, Shift):
        return (".clock", ".reset")
    if isinstance(token, Counter) and token.counter_type == "count_up":
        return (".down", ".reset")
    return None


def _call_name(token: AfInstruction) -> str:
    if isinstance(token, Drum):
        return f"{token.drum_kind}_drum()"
    if isinstance(token, Counter):
        return f"{token.counter_type}()"
    return "shift()"


def _consume_pinned_row(block: _ActiveBlock, row: _ParsedRow, order: tuple[str, ...]) -> bool:
    """Absorb pin rows (in pin order) and the leg rows between them.

    Nothing after the last pin belongs to the block: legs under it sit below
    the box.  Blank rows after an earlier pin are absorbed even when no later
    pin follows; ``_finalize_pinned_block`` hands back the ones past the box.
    """
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
        raise ConvertError(f"Pin token {pin_name!r} is not supported for {_call_name(block.token)}")
    remaining = order[order.index(seen[-1]) + 1 :] if seen else order
    if pin_name not in remaining:
        raise ConvertError(
            f"Pin token {pin_name!r} is out of order or repeated for "
            f"{_call_name(block.token)}: pins go {', '.join(f'{p}()' for p in order)}"
        )
    block.continuations.append(row)
    return True


def _consume_active_row(block: _ActiveBlock, row: _ParsedRow) -> bool:
    """Consume a continuation row for the active block when it belongs there."""
    order = _pin_order(block.token)
    if order is not None:
        return _consume_pinned_row(block, row, order)

    if len(block.continuations) >= _max_continuations(block):
        return False

    # .reset() occupies the last row of a counter span, so nothing after it
    # belongs to the block — following rows are floating rows below the span
    # (e.g. the OR-leg of the reset branch).
    if isinstance(block.token, Counter) and any(
        c.kind == "pin" and c.pin_name == ".reset" for c in block.continuations
    ):
        return False

    if row.kind == "blank":
        block.continuations.append(row)
        return True

    if row.kind == "pin":
        pin_name = cast(str, row.pin_name)
        if isinstance(block.token, Counter):
            if pin_name not in {".down", ".reset"}:
                raise ConvertError(
                    f"Pin token {pin_name!r} is not supported for {block.token.counter_type}()"
                )
            block.continuations.append(row)
            return True

        # Timers remain lenient for non-.reset() pin rows: absorb them as blank rows.
        if isinstance(block.token, Timer):
            block.continuations.append(row)
            return True

    if isinstance(block.token, Counter) and block.token.counter_type == "count_down":
        if row.kind == "nop":
            block.continuations.append(row)
            return True

    return False


def _finalize_timer_block(block: _ActiveBlock) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand one timer block back to its decoded 2-row span."""
    timer = cast(Timer, block.token)
    continuation_conditions = _blank_condition_row()
    if block.continuations:
        continuation = block.continuations[0]
        if continuation.kind == "nop":
            raise ConvertError("Timer continuation rows cannot use NOP")
        continuation_conditions = continuation.conditions
        if continuation.kind == "pin" and continuation.pin_name in _RETENTIVE_PINS:
            timer = replace(timer, retained=True)

    return [block.main_conditions, continuation_conditions], [timer, ""]


def _finalize_pinned_block(
    block: _ActiveBlock, order: tuple[str, ...]
) -> tuple[list[list[ConditionToken]], list[AfToken], list[_ParsedRow]]:
    """Lay out a pinned block, placing each pin on its own row.

    Rows between pins are OR legs of the pin above.  An unused pin still
    takes a row of its own, below those legs (as CLICK lays out a leg added
    with Insert Row: Reset 1, leg 2, unused Jump 3, Jog 4).  Blank rows just
    above the next pin are read as the unused pins' rows, not legs.  Unused
    pins after the last used one sit directly under it, and the box ends at
    the last pin's row; absorbed rows past it are returned as the tail.
    """
    token = block.token
    rows = [block.main_conditions]
    pin_rows: list[int] = []
    pins: dict[str, _ParsedRow] = {}
    pending = list(block.continuations)
    prev = 0
    unused = 0
    for slot in order:
        j = next((i for i, row in enumerate(pending) if row.kind == "pin"), None)
        if j is None or pending[j].pin_name != slot:
            unused += 1
            continue
        gap = pending[:j]
        blank = 0
        while blank < min(unused, len(gap)) and _is_blank_row(gap[-1 - blank].conditions):
            blank += 1
        rows.extend(row.conditions for row in gap)
        rows.extend(_blank_condition_row() for _ in range(unused - blank))
        pin_rows.extend(range(len(rows) - unused, len(rows)))
        prev = len(rows)
        rows.append(pending[j].conditions)
        pin_rows.append(prev)
        pins[slot] = pending[j]
        pending = pending[j + 1 :]
        unused = 0
    pin_rows.extend(range(prev + 1, prev + 1 + unused))
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

    token = _apply_pins(token, pins, tuple(pin_rows))
    return rows, [token, *([""] * (len(rows) - 1))], tail


def _apply_pins(
    token: AfInstruction, pins: dict[str, _ParsedRow], pin_rows: tuple[int, ...]
) -> AfInstruction:
    """Set the pin flags a block's pin rows imply, plus each pin's row."""
    if isinstance(token, Drum):
        if ".reset" not in pins:
            raise ConvertError("Drum requires a .reset() pin row")
        jump = pins.get(".jump")
        if jump is not None:
            target = jump.pin_args[0] if jump.pin_args else ""
            token = replace(token, jump_enabled=True, jump_target=target)
        if ".jog" in pins:
            token = replace(token, jog_enabled=True)
        return replace(token, pin_rows=cast(tuple[int, int, int], pin_rows))
    if isinstance(token, Counter):
        if ".reset" not in pins:
            raise ConvertError(f"{token.counter_type} requires a .reset() pin row")
        token = replace(token, reset_enabled=True, down_enabled=".down" in pins)
        return replace(token, pin_rows=cast(tuple[int, int], pin_rows))
    return replace(cast(Shift, token), pin_rows=cast(tuple[int, int], pin_rows))


def _finalize_count_down_block(
    block: _ActiveBlock,
) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand one count_down block back to its decoded 3-row span."""
    counter = cast(Counter, block.token)
    explicit_bridge_conditions: list[ConditionToken] | None = None
    reset_conditions: list[ConditionToken] | None = None

    for row in block.continuations:
        if row.kind == "pin":
            pin_name = cast(str, row.pin_name)
            if pin_name == ".down":
                raise ConvertError("count_down does not support .down()")
            if pin_name == ".reset":
                counter = replace(counter, reset_enabled=True)
                reset_conditions = row.conditions
                continue

        if row.kind == "nop":
            if block.leading_blank_conditions is not None:
                raise ConvertError("count_down block cannot mix a leading blank top row with NOP")
            if explicit_bridge_conditions is not None:
                raise ConvertError("count_down block uses more than one bridge row")
            explicit_bridge_conditions = row.conditions
            continue

        if block.leading_blank_conditions is None and explicit_bridge_conditions is None:
            explicit_bridge_conditions = row.conditions
            continue
        if reset_conditions is None:
            reset_conditions = row.conditions
            continue

    if not counter.reset_enabled:
        raise ConvertError(f"{counter.counter_type} requires a .reset() pin row")

    if reset_conditions is None:
        reset_conditions = _blank_condition_row()

    if block.leading_blank_conditions is not None:
        condition_rows = [
            block.leading_blank_conditions,
            block.main_conditions,
            reset_conditions,
        ]
    elif explicit_bridge_conditions is not None:
        condition_rows = [
            block.main_conditions,
            explicit_bridge_conditions,
            reset_conditions,
        ]
    else:
        condition_rows = [
            _blank_condition_row(),
            block.main_conditions,
            reset_conditions,
        ]

    return condition_rows, [counter, "NOP", ""]


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
    order = _pin_order(block.token)
    if order is not None:
        return _finalize_pinned_block(block, order)
    if isinstance(block.token, Timer):
        rows, afs = _finalize_timer_block(block)
    elif isinstance(block.token, Counter):
        rows, afs = _finalize_count_down_block(block)
    else:
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
            leading_blank_conditions: list[ConditionToken] | None = None
            if isinstance(parsed.token, Counter) and parsed.token.counter_type == "count_down":
                if plain_rows and plain_rows[-1].kind == "blank":
                    leading_blank_conditions = plain_rows.pop().conditions
            _flush_plain_rows(plain_rows, condition_rows, af_tokens)
            active_block = _start_active_block(
                parsed,
                leading_blank_conditions=leading_blank_conditions,
            )
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
