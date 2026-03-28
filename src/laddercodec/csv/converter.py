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

import re
from typing import Literal

from ..encode import AfToken, ConditionToken
from ..instructions import (
    BlockCopy,
    Coil,
    CompareContact,
    Contact,
    Copy,
    Fill,
    RawInstruction,
    Timer,
)
from ..instructions.coil import COIL_NAME_TO_TYPE
from ..instructions.raw import find_blob_boundary
from ..instructions.timer import TIMER_UNIT_TO_INDEX
from ..model import AfInstruction, InstructionType, _validate_operand
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
from .token_parser import parse_af_token as _parse_af_token

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
    "copy": 2,
    "blockcopy": 2,
    "fill": 2,
}

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


def _parse_coil_arg(arg: str) -> tuple[str, str | None, bool]:
    """Parse a coil inner argument into (operand, range_end, immediate).

    Handles ``immediate()`` wrapper and ``..`` range syntax.
    """
    immediate = False
    inner = re.fullmatch(r"immediate\((.+)\)", arg)
    if inner:
        immediate = True
        arg = inner.group(1).strip()

    if ".." in arg:
        parts = [p.strip() for p in arg.split("..")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Cannot parse coil range: {arg!r}")
        return _validate_operand(parts[0]), _validate_operand(parts[1]), immediate

    return _validate_operand(arg), None, immediate


def _parse_range(arg: str) -> tuple[str, str]:
    """Split ``"DS28..DS31"`` into ``("DS28", "DS31")``."""
    if ".." not in arg:
        raise ValueError(f"Expected range with '..': {arg!r}")
    parts = [p.strip() for p in arg.split("..")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Cannot parse range: {arg!r}")
    return parts[0], parts[1]


_CONVERT_FORMATS = frozenset({"to_text", "to_value", "to_binary", "to_ascii"})


def _parse_convert_value(raw: str) -> tuple[str, dict[str, str]]:
    """Parse a ``convert=`` kwarg value, returning *(format, text_opts)*.

    Examples: ``to_value``, ``to_text(suppress_zero=0,exponential=1)``.
    """
    parsed = _parse_af_token(raw.strip())
    if not isinstance(parsed, AfCall) or parsed.name not in _CONVERT_FORMATS:
        raise ValueError(f"Cannot parse convert value: {raw!r}")

    fmt = parsed.name[3:]  # "text", "value", "binary", "ascii"

    if fmt != "text":
        if parsed.args or parsed.kwargs:
            raise ValueError(f"to_{fmt} takes no arguments: {raw!r}")
        return fmt, {}

    return "text", dict(parsed.kwargs)


def _af_call_to_token(call: AfCall, *, strict: bool = True) -> AfToken:
    """Convert a parsed AF call node to an encode-ready token."""
    name = call.name

    if name in COIL_NAME_TO_TYPE:
        if len(call.args) != 1:
            raise ValueError(
                f"Coil {name!r} expects exactly 1 positional arg, got {len(call.args)}"
            )
        operand, range_end, immediate = _parse_coil_arg(call.args[0])
        oneshot = call.kwargs.get("oneshot") == "1"
        return Coil(
            type=COIL_NAME_TO_TYPE[name],
            operand=operand,
            range_end=range_end,
            immediate=immediate,
            oneshot=oneshot,
        )

    if name in ("on_delay", "off_delay"):
        timer_type: Literal["on_delay", "off_delay"] = name  # type: ignore[assignment]
        if len(call.args) != 2:
            raise ValueError(f"{name} expects 2 positional args (done, acc), got {len(call.args)}")
        done_bit, current = call.args
        setpoint = call.kwargs.get("preset", "")
        unit = call.kwargs.get("unit", "")
        if not setpoint or not unit:
            raise ValueError(f"{name} missing preset or unit kwargs")
        if unit not in TIMER_UNIT_TO_INDEX:
            raise ValueError(f"Unknown timer unit: {unit!r}")
        return Timer(
            timer_type=timer_type,
            done_bit=done_bit,
            current=current,
            setpoint=setpoint,
            unit=unit,
        )

    if name == "copy":
        if len(call.args) != 2:
            raise ValueError(f"copy expects 2 positional args (source, dest), got {len(call.args)}")
        source, destination = call.args
        oneshot = call.kwargs.get("oneshot") == "1"

        # Parse convert= kwarg
        convert_raw = call.kwargs.get("convert", "")
        if convert_raw:
            fmt, text_opts = _parse_convert_value(convert_raw)
        else:
            fmt, text_opts = "none", {}

        suppress_zero = text_opts.get("suppress_zero", "0")
        exponential = text_opts.get("exponential", "0")
        term_val = text_opts.get("termination_code", "0")
        if term_val == "none":
            term_val = "0"

        return Copy(
            source=source,
            destination=destination,
            format=fmt,
            oneshot=oneshot,
            suppress_zero=suppress_zero,
            exponential=exponential,
            termination_code=term_val,
        )

    if name == "blockcopy":
        if len(call.args) != 2:
            raise ValueError(
                f"blockcopy expects 2 positional args (src_range, dest_range), got {len(call.args)}"
            )
        src_start, src_end = _parse_range(call.args[0])
        dest_start, dest_end = _parse_range(call.args[1])
        oneshot = call.kwargs.get("oneshot") == "1"
        convert_raw = call.kwargs.get("convert", "")
        if convert_raw:
            fmt, _ = _parse_convert_value(convert_raw)
        else:
            fmt = "none"
        return BlockCopy(
            source_start=src_start,
            source_end=src_end,
            dest_start=dest_start,
            dest_end=dest_end,
            format=fmt,
            oneshot=oneshot,
        )

    if name == "fill":
        if len(call.args) != 2:
            raise ValueError(
                f"fill expects 2 positional args (value, dest_range), got {len(call.args)}"
            )
        value = call.args[0]
        dest_start, dest_end = _parse_range(call.args[1])
        oneshot = call.kwargs.get("oneshot") == "1"
        return Fill(
            value=value,
            dest_start=dest_start,
            dest_end=dest_end,
            oneshot=oneshot,
        )

    if name == "raw":
        if len(call.args) != 2:
            raise ValueError(f"raw() expects 2 positional args, got {len(call.args)}")
        class_name = call.args[0]
        blob = bytes.fromhex(call.args[1])
        try:
            _, _, part_count = find_blob_boundary(blob)
        except (ValueError, IndexError):
            part_count = 1
        return RawInstruction(class_name=class_name, blob=blob, part_count=part_count)

    if strict:
        raise ValueError(f"Unsupported AF instruction: {name!r}")
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
            conds = [condition_node_to_token(n) for n in row.condition_nodes]
            condition_rows.append(conds)
            af_tokens.append("")
            continue

        # Normal row — convert conditions.
        conds = [condition_node_to_token(n) for n in row.condition_nodes]
        condition_rows.append(conds)

        # Convert AF token.
        token = af_node_to_token(af_node, strict=strict)
        af_tokens.append(token)
        if row_idx == 0 and isinstance(af_node, AfCall) and af_node.name.upper() != "NOP":
            parent_af_name = af_node.name
            if isinstance(token, Timer):
                parent_timer = token

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
    is_tall = isinstance(af0, AfInstruction) and af0.cell_params().get("visual_rows", 1) > 1
    if not is_tall:
        return logical_rows, condition_rows, af_tokens

    # Strip trailing blank rows (from the end, in case of future >2-row tall).
    while len(condition_rows) > 1 and _is_blank_row(condition_rows[-1], af_tokens[-1]):
        condition_rows = condition_rows[:-1]
        af_tokens = af_tokens[:-1]

    return len(condition_rows), condition_rows, af_tokens
