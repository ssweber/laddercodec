"""RungAst → encode_rung() arguments converter.

Converts parsed CSV AST into the (logical_rows, condition_rows, af_tokens)
tuple consumed by ``encode_rung()``.  Handles:

- Condition/contact/compare token conversion to model objects
- AF token conversion (coils, timers, NOP)
- Pin continuation rows (``.reset()``, ``.down()``, etc.) — absorbed into
  the parent instruction rather than emitted as separate rows
- Auto-padding: tall AF instructions (timers, counters) get a blank
  continuation row appended when the user provides only one row

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

Some AF instructions occupy more than one grid row visually (timers = 2).
If the user CSV has only the instruction row, a blank padding row is
auto-appended so ``encode_rung()`` receives the correct ``logical_rows``.
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
_BLOCK_FAMILIES = frozenset({"timer", "counter", "shift", "drum"})


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

    family_name: str
    token: Timer | Counter | Shift | Drum
    main_conditions: list[ConditionToken]
    leading_blank_conditions: list[ConditionToken] | None = None
    continuations: list[_ParsedRow] = field(default_factory=list)


def _blank_condition_row() -> list[ConditionToken]:
    """Return one all-blank condition row."""
    return cast(list[ConditionToken], [""] * CONDITION_COLUMNS)


def _parse_rung_row(row: object, *, strict: bool) -> _ParsedRow:
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
    if family is not None and family.family_name in _BLOCK_FAMILIES:
        return _ParsedRow(
            conditions=conds,
            kind="block_main",
            token=token,
            family_name=family.family_name,
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
    if not isinstance(row.token, (Timer, Counter, Shift, Drum)):
        raise AssertionError("block_main row must carry a timer/counter/shift/drum token")
    return _ActiveBlock(
        family_name=cast(str, row.family_name),
        token=row.token,
        main_conditions=row.conditions,
        leading_blank_conditions=leading_blank_conditions,
    )


def _consume_active_row(block: _ActiveBlock, row: _ParsedRow) -> bool:
    """Consume a continuation row for the active block when it belongs there."""
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

        if isinstance(block.token, Drum):
            if pin_name not in {".reset", ".jump", ".jog"}:
                raise ConvertError(
                    f"Pin token {pin_name!r} is not supported for {block.token.drum_kind}_drum()"
                )
            block.continuations.append(row)
            return True

        if isinstance(block.token, Shift):
            if pin_name not in {".clock", ".reset"}:
                raise ConvertError(f"Pin token {pin_name!r} is not supported for shift()")
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
    if len(block.continuations) > 1:
        raise ConvertError("Timer block uses more than one continuation row")

    continuation_conditions = _blank_condition_row()
    if block.continuations:
        continuation = block.continuations[0]
        if continuation.kind == "nop":
            raise ConvertError("Timer continuation rows cannot use NOP")
        continuation_conditions = continuation.conditions
        if continuation.kind == "pin" and continuation.pin_name in _RETENTIVE_PINS:
            timer = replace(timer, retained=True)

    return [block.main_conditions, continuation_conditions], [timer, ""]


def _finalize_count_up_block(
    block: _ActiveBlock,
) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand one count_up block back to its decoded 3-row span."""
    counter = cast(Counter, block.token)
    middle_conditions: list[ConditionToken] | None = None
    reset_conditions: list[ConditionToken] | None = None

    for row in block.continuations:
        if row.kind == "nop":
            raise ConvertError("count_up does not support NOP bridge rows")

        if row.kind == "pin":
            pin_name = cast(str, row.pin_name)
            if pin_name == ".down":
                counter = replace(counter, down_enabled=True)
                middle_conditions = row.conditions
                continue
            if pin_name == ".reset":
                counter = replace(counter, reset_enabled=True)
                reset_conditions = row.conditions
                continue

        if middle_conditions is None:
            middle_conditions = row.conditions
            continue
        if reset_conditions is None:
            reset_conditions = row.conditions
            continue
        raise ConvertError("count_up block uses more than two continuation rows")

    if not counter.reset_enabled:
        raise ConvertError(f"{counter.counter_type} requires a .reset() pin row")

    if middle_conditions is None:
        middle_conditions = _blank_condition_row()
    if reset_conditions is None:
        reset_conditions = _blank_condition_row()

    return [block.main_conditions, middle_conditions, reset_conditions], [counter, "", ""]


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
        raise ConvertError("count_down block uses more than two continuation rows")

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


def _finalize_counter_block(
    block: _ActiveBlock,
) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand one counter block back to its decoded 3-row span."""
    counter = cast(Counter, block.token)
    if counter.counter_type == "count_up":
        return _finalize_count_up_block(block)
    return _finalize_count_down_block(block)


def _finalize_shift_block(block: _ActiveBlock) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand one shift block back to its decoded 3-row span."""
    shift = cast(Shift, block.token)
    clock_conditions: list[ConditionToken] | None = None
    reset_conditions: list[ConditionToken] | None = None

    for row in block.continuations:
        if row.kind == "nop":
            raise ConvertError("Shift continuation rows cannot use NOP")

        if row.kind == "pin":
            pin_name = cast(str, row.pin_name)
            if pin_name == ".clock":
                clock_conditions = row.conditions
                continue
            if pin_name == ".reset":
                reset_conditions = row.conditions
                continue

        if clock_conditions is None:
            clock_conditions = row.conditions
            continue
        if reset_conditions is None:
            reset_conditions = row.conditions
            continue
        raise ConvertError("Shift block uses more than two continuation rows")

    if clock_conditions is None:
        clock_conditions = _blank_condition_row()
    if reset_conditions is None:
        reset_conditions = _blank_condition_row()

    return [block.main_conditions, clock_conditions, reset_conditions], [shift, "", ""]


def _finalize_drum_block(block: _ActiveBlock) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand one drum block back to its decoded 4-row span."""
    drum = cast(Drum, block.token)
    reset_conditions: list[ConditionToken] | None = None
    jump_conditions: list[ConditionToken] | None = None
    jog_conditions: list[ConditionToken] | None = None

    for row in block.continuations:
        if row.kind == "nop":
            raise ConvertError("Drum continuation rows cannot use NOP")

        if row.kind == "pin":
            pin_name = cast(str, row.pin_name)
            if pin_name == ".reset":
                reset_conditions = row.conditions
                continue
            if pin_name == ".jump":
                jump_target = row.pin_args[0] if row.pin_args else ""
                drum = replace(drum, jump_enabled=True, jump_target=jump_target)
                jump_conditions = row.conditions
                continue
            if pin_name == ".jog":
                drum = replace(drum, jog_enabled=True)
                jog_conditions = row.conditions
                continue

        if reset_conditions is None:
            reset_conditions = row.conditions
            continue
        if jump_conditions is None:
            jump_conditions = row.conditions
            continue
        if jog_conditions is None:
            jog_conditions = row.conditions
            continue
        raise ConvertError("Drum block uses more than three continuation rows")

    if reset_conditions is None:
        raise ConvertError("Drum requires a .reset() pin row")

    if jump_conditions is None:
        jump_conditions = _blank_condition_row()
    if jog_conditions is None:
        jog_conditions = _blank_condition_row()

    return [
        block.main_conditions,
        reset_conditions,
        jump_conditions,
        jog_conditions,
    ], [drum, "", "", ""]


def _finalize_active_block(block: _ActiveBlock) -> tuple[list[list[ConditionToken]], list[AfToken]]:
    """Expand the current active block into decode-ready rows/tokens."""
    if isinstance(block.token, Timer):
        return _finalize_timer_block(block)
    if isinstance(block.token, Counter):
        return _finalize_counter_block(block)
    if isinstance(block.token, Shift):
        return _finalize_shift_block(block)
    if isinstance(block.token, Drum):
        return _finalize_drum_block(block)
    raise AssertionError(f"Unsupported active block token: {type(block.token).__name__}")


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
            block_conditions, block_afs = _finalize_active_block(active_block)
            condition_rows.extend(block_conditions)
            af_tokens.extend(block_afs)
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
        block_conditions, block_afs = _finalize_active_block(active_block)
        condition_rows.extend(block_conditions)
        af_tokens.extend(block_afs)

    _flush_plain_rows(plain_rows, condition_rows, af_tokens)

    # --- Auto-pad for tall instructions ---
    af0 = af_tokens[0] if af_tokens else ""
    if isinstance(af0, AfInstruction):
        spec = get_af_family_for_token(af0)
        min_rows = spec.min_csv_rows if spec is not None else 1
        while len(condition_rows) < min_rows:
            condition_rows.append(cast(list[ConditionToken], [""] * CONDITION_COLUMNS))
            af_tokens.append("")

    logical_rows = len(condition_rows)
    return logical_rows, condition_rows, af_tokens, comment


# ---------------------------------------------------------------------------
# Decode-side: strip blank padding rows from tall instructions
# ---------------------------------------------------------------------------


def _is_blank_row(
    conditions: list[object],
    af: object,
) -> bool:
    """Return True if all conditions are blank and AF is blank."""
    if af != "":
        return False
    return all(c == "" for c in conditions)


def strip_tall_padding(
    logical_rows: int,
    condition_rows: list[list[object]],
    af_tokens: list[object],
) -> tuple[int, list[list[object]], list[object]]:
    """Remove trailing blank rows that are just visual padding for tall instructions.

    After decoding, a timer rung may have a trailing all-blank row that
    exists only because the timer cell is visually tall.  This function
    strips such rows so the decoded output matches the user's CSV input.

    Rows with any content (wires, contacts, etc.) are kept.
    """
    if logical_rows < 2:
        return logical_rows, condition_rows, af_tokens

    # Check if row 0 has a tall AF instruction.
    af0 = af_tokens[0]
    is_tall = isinstance(af0, AfInstruction) and af0.cell_params().get("visual_rows", 1) > 1
    if not is_tall:
        return logical_rows, condition_rows, af_tokens

    # Strip trailing blank rows (from the end, in case of future >2-row tall).
    while len(condition_rows) > 1 and _is_blank_row(condition_rows[-1], af_tokens[-1]):
        condition_rows = condition_rows[:-1]
        af_tokens = af_tokens[:-1]

    return len(condition_rows), condition_rows, af_tokens
