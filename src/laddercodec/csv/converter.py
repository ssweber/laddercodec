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

from dataclasses import replace
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

    # --- Classify rows: instruction rows vs pin rows ---
    condition_rows: list[list[ConditionToken]] = []
    af_tokens: list[AfToken] = []
    parent_timer: Timer | None = None
    parent_counter: Counter | None = None
    parent_shift: Shift | None = None
    parent_drum: Drum | None = None
    counter_up_conditions: list[ConditionToken] | None = None
    counter_top_conditions: list[ConditionToken] | None = None
    counter_bridge_conditions: list[ConditionToken] | None = None
    counter_down_conditions: list[ConditionToken] | None = None
    counter_reset_conditions: list[ConditionToken] | None = None
    shift_data_conditions: list[ConditionToken] | None = None
    shift_clock_conditions: list[ConditionToken] | None = None
    shift_reset_conditions: list[ConditionToken] | None = None
    drum_reset_conditions: list[ConditionToken] | None = None
    drum_jump_conditions: list[ConditionToken] | None = None
    drum_jog_conditions: list[ConditionToken] | None = None

    for row_idx, row in enumerate(rung.rows):
        af_node = row.af_node

        # Check for pin row (dot-prefixed AF token).
        if isinstance(af_node, AfCall) and af_node.name.startswith("."):
            pin_name = af_node.name
            if pin_name not in KNOWN_PIN_NAMES:
                raise ConvertError(f"Unknown pin token: {pin_name!r}")

            conds = [condition_node_to_token(n) for n in row.condition_nodes]

            if parent_counter is not None:
                if pin_name == ".down":
                    if parent_counter.counter_type != "count_up":
                        raise ConvertError(".down() is only valid for count_up()")
                    counter_down_conditions = conds
                    parent_counter = replace(parent_counter, down_enabled=True)
                    af_tokens[0] = parent_counter
                    continue

                if pin_name == ".reset":
                    counter_reset_conditions = conds
                    parent_counter = replace(parent_counter, reset_enabled=True)
                    af_tokens[0] = parent_counter
                    continue

                raise ConvertError(
                    f"Pin token {pin_name!r} is not supported for {parent_counter.counter_type}()"
                )

            if parent_drum is not None:
                if pin_name == ".reset":
                    drum_reset_conditions = conds
                    continue
                if pin_name == ".jump":
                    jump_target = af_node.args[0] if af_node.args else ""
                    parent_drum = replace(parent_drum, jump_enabled=True, jump_target=jump_target)
                    af_tokens[0] = parent_drum
                    drum_jump_conditions = conds
                    continue
                if pin_name == ".jog":
                    parent_drum = replace(parent_drum, jog_enabled=True)
                    af_tokens[0] = parent_drum
                    drum_jog_conditions = conds
                    continue
                raise ConvertError(
                    f"Pin token {pin_name!r} is not supported for {parent_drum.drum_kind}_drum()"
                )

            if parent_shift is not None:
                if pin_name == ".clock":
                    shift_clock_conditions = conds
                    continue
                if pin_name == ".reset":
                    shift_reset_conditions = conds
                    continue
                raise ConvertError(f"Pin token {pin_name!r} is not supported for shift()")

            if pin_name in _RETENTIVE_PINS and parent_timer is not None:
                # .reset() makes the parent timer retentive.
                parent_timer = replace(parent_timer, retained=True)
                # Update af_tokens[0] with the modified timer.
                af_tokens[0] = parent_timer

            # Pin row contributes its conditions/wires as a normal data row,
            # but the AF token becomes blank (no separate instruction).
            condition_rows.append(conds)
            af_tokens.append("")
            continue

        # Normal row — convert conditions.
        conds = [condition_node_to_token(n) for n in row.condition_nodes]

        # Convert AF token.
        token = af_node_to_token(af_node, strict=strict)
        if (
            parent_counter is None
            and isinstance(token, Counter)
            and token.counter_type == "count_down"
            and row_idx > 0
        ):
            if len(condition_rows) != 1 or af_tokens != [""]:
                raise ConvertError("count_down visual layout requires exactly one blank-AF top row")
            counter_top_conditions = condition_rows.pop()
            af_tokens.pop()
            condition_rows.append(conds)
            af_tokens.append(token)
            parent_counter = token
            counter_up_conditions = conds
            continue

        if (
            parent_counter is not None
            and parent_counter.counter_type == "count_down"
            and row_idx > 0
            and counter_bridge_conditions is None
            and token in ("", "NOP")
        ):
            counter_bridge_conditions = conds
            continue

        condition_rows.append(conds)
        af_tokens.append(token)
        if row_idx == 0 and isinstance(af_node, AfCall) and af_node.name.upper() != "NOP":
            if isinstance(token, Timer):
                parent_timer = token
            if isinstance(token, Counter):
                parent_counter = token
                counter_up_conditions = conds
            if isinstance(token, Shift):
                parent_shift = token
                shift_data_conditions = conds
            if isinstance(token, Drum):
                parent_drum = token

    # --- Drum row shaping ---
    if parent_drum is not None:
        if drum_reset_conditions is None:
            raise ConvertError("Drum requires a .reset() pin row")

        if len(condition_rows) != 1:
            raise ConvertError(
                "Drum pin rows must use .reset()/.jump()/.jog() tokens "
                "(blank-AF continuation rows are unsupported)"
            )

        main_conds = condition_rows[0]
        blank_row = cast(list[ConditionToken], [""] * CONDITION_COLUMNS)

        condition_rows = [
            main_conds,
            drum_reset_conditions,
            drum_jump_conditions if drum_jump_conditions is not None else blank_row,
            drum_jog_conditions if drum_jog_conditions is not None else blank_row,
        ]
        af_tokens = [parent_drum, "", "", ""]

    # --- Counter row shaping ---
    if parent_counter is not None:
        if counter_up_conditions is None:
            raise ConvertError("Counter rung is missing a primary row")

        if len(condition_rows) != 1:
            raise ConvertError(
                "Counter pin rows must use .down()/.reset() tokens (blank-AF continuation rows are unsupported)"
            )

        if counter_reset_conditions is None:
            raise ConvertError(f"{parent_counter.counter_type} requires a .reset() pin row")

        assert counter_up_conditions is not None
        assert counter_reset_conditions is not None
        blank_row = cast(list[ConditionToken], [""] * CONDITION_COLUMNS)

        if parent_counter.counter_type == "count_up":
            if parent_counter.down_enabled:
                if counter_down_conditions is None:
                    raise ConvertError("count_up with .down() is missing down conditions")
                middle_row = counter_down_conditions
            else:
                middle_row = blank_row
            condition_rows = [counter_up_conditions, middle_row, counter_reset_conditions]
            af_tokens = [parent_counter, "", ""]
        else:
            if counter_down_conditions is not None:
                raise ConvertError("count_down does not support .down()")
            if counter_top_conditions is not None:
                condition_rows = [
                    counter_top_conditions,
                    counter_up_conditions,
                    counter_reset_conditions,
                ]
            elif counter_bridge_conditions is not None:
                condition_rows = [
                    counter_up_conditions,
                    counter_bridge_conditions,
                    counter_reset_conditions,
                ]
            else:
                condition_rows = [blank_row, counter_up_conditions, counter_reset_conditions]
            af_tokens = [parent_counter, "NOP", ""]

    # --- Shift row shaping ---
    if parent_shift is not None:
        if shift_data_conditions is None:
            raise ConvertError("Shift rung is missing a primary row")

        if len(condition_rows) != 1:
            raise ConvertError(
                "Shift pin rows must use .clock()/.reset() tokens (blank-AF continuation rows are unsupported)"
            )

        clock_conditions = (
            shift_clock_conditions
            if shift_clock_conditions is not None
            else cast(list[ConditionToken], [""] * CONDITION_COLUMNS)
        )
        reset_conditions = (
            shift_reset_conditions
            if shift_reset_conditions is not None
            else cast(list[ConditionToken], [""] * CONDITION_COLUMNS)
        )
        condition_rows = [shift_data_conditions, clock_conditions, reset_conditions]
        af_tokens = [parent_shift, "", ""]

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
