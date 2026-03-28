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

from ..encode import AfToken, ConditionToken
from ..instructions import Coil, CompareContact, Contact, Timer
from ..model import InstructionType
from .ast import (
    AfBlank,
    AfCall,
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

#: All recognised pin names (extend as new instructions are supported).
_KNOWN_PINS = frozenset({".reset", ".down", ".clock", ".jump", ".jog"})

#: AF instruction names whose cells are taller than one grid row.
#: Value = minimum grid rows the instruction needs.
_TALL_AF: dict[str, int] = {
    "on_delay": 2,
    "off_delay": 2,
}

# ---------------------------------------------------------------------------
# Condition / AF token conversion helpers
# ---------------------------------------------------------------------------

CONDITION_COLUMNS = 31


def _condition_node_to_token(node: object) -> ConditionToken:
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
        if node.negated:
            itype = InstructionType.CONTACT_NC
        else:
            itype = InstructionType.CONTACT_NO
        return Contact(type=itype, operand=node.operand, immediate=node.immediate)
    if isinstance(node, EdgeCondition):
        return Contact(
            type=InstructionType.CONTACT_EDGE,
            operand=node.operand,
            edge_kind=node.kind,
        )
    if isinstance(node, ComparisonCondition):
        return CompareContact(op=node.op, left=node.left, right=node.right)
    if isinstance(node, GenericCondition):
        raise ValueError(f"Cannot convert generic condition to encode token: {node.raw!r}")
    raise TypeError(f"Unknown condition node type: {type(node).__name__}")


def _af_call_to_token(call: AfCall) -> AfToken:
    """Convert a parsed AF call node to an encode-ready token."""
    name = call.name

    if name in ("out", "latch", "reset"):
        # Coil.from_csv_token expects positional-only form: out(Y001)
        positional_token = f"{name}({','.join(call.args)})"
        return Coil.from_csv_token(positional_token)

    if name in ("on_delay", "off_delay"):
        return Timer.from_csv_token(call.to_token())

    raise ValueError(f"Unsupported AF instruction: {name!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ConvertError(ValueError):
    """Raised when a RungAst cannot be converted to encode arguments."""


def convert_rung(
    rung: RungAst,
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
    parent_af_name: str | None = None  # name of the AF instruction on row 0
    parent_timer: Timer | None = None

    for row_idx, row in enumerate(rung.rows):
        af_node = row.af_node

        # Check for pin row (dot-prefixed AF token).
        if isinstance(af_node, AfCall) and af_node.name.startswith("."):
            pin_name = af_node.name
            if pin_name not in _KNOWN_PINS:
                raise ConvertError(f"Unknown pin token: {pin_name!r}")

            if pin_name in _RETENTIVE_PINS and parent_timer is not None:
                # .reset() makes the parent timer retentive.
                parent_timer = Timer(
                    timer_type=parent_timer.timer_type,
                    done_bit=parent_timer.done_bit,
                    current=parent_timer.current,
                    setpoint=parent_timer.setpoint,
                    unit=parent_timer.unit,
                    retained=True,
                )
                # Update af_tokens[0] with the modified timer.
                af_tokens[0] = parent_timer

            # Pin row contributes its conditions/wires as a normal data row,
            # but the AF token becomes blank (no separate instruction).
            conds = [_condition_node_to_token(n) for n in row.condition_nodes]
            condition_rows.append(conds)
            af_tokens.append("")
            continue

        # Normal row — convert conditions.
        conds = [_condition_node_to_token(n) for n in row.condition_nodes]
        condition_rows.append(conds)

        # Convert AF token.
        if isinstance(af_node, AfBlank):
            af_tokens.append("")
        elif isinstance(af_node, AfCall):
            if af_node.name.upper() == "NOP":
                af_tokens.append("NOP")
            else:
                token = _af_call_to_token(af_node)
                af_tokens.append(token)
                if row_idx == 0:
                    parent_af_name = af_node.name
                    if isinstance(token, Timer):
                        parent_timer = token
        else:
            af_tokens.append("")

    # --- Auto-pad for tall instructions ---
    if parent_af_name in _TALL_AF:
        min_rows = _TALL_AF[parent_af_name]
        while len(condition_rows) < min_rows:
            condition_rows.append([""] * CONDITION_COLUMNS)
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
    is_tall = isinstance(af0, Timer)
    if not is_tall:
        return logical_rows, condition_rows, af_tokens

    # Strip trailing blank rows (from the end, in case of future >2-row tall).
    while len(condition_rows) > 1 and _is_blank_row(condition_rows[-1], af_tokens[-1]):
        condition_rows = condition_rows[:-1]
        af_tokens = af_tokens[:-1]

    return len(condition_rows), condition_rows, af_tokens
