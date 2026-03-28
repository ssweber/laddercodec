"""CSV writer — decode binary to CSV v2 format.

Converts ``DecodedRung`` objects (from ``decode_rung()`` / ``decode_multi_rung()``)
into canonical CSV files that round-trip through ``read_golden_csv()`` and back
to ``encode_rung()``.

Public API
----------

    decode_to_csv(data, path)           — single or multi-rung binary → CSV file
    write_decoded_csv(path, rungs)      — list[DecodedRung] → CSV file
    decoded_rung_to_rows(rung)          — DecodedRung → list of CSV row lists

Pin row reconstruction
----------------------

The binary format stores timer retention as a flag in the timer blob.
The CSV format represents it as a ``.reset()`` pin row.  When a retained
timer is decoded, the writer emits a ``.reset()`` row using the conditions
from the timer's second grid row (which carried the reset-enable branch).

Tall instruction padding
------------------------

Non-retained timers have a trailing blank row for visual height.  This row
is stripped before writing — the forward path's auto-padding restores it.
"""

from __future__ import annotations

import csv as csv_mod
from pathlib import Path

from ..decode import (
    DecodedRung,
    UnknownCondition,
    UnknownInstruction,
    decode_multi_rung,
    decode_rung,
)
from ..instructions import Coil, CompareContact, Contact, RawInstruction, Timer
from .contract import CSV_HEADER


class WriterError(ValueError):
    """Raised when a decoded rung cannot be serialized to CSV."""


# ---------------------------------------------------------------------------
# Token serialization
# ---------------------------------------------------------------------------


def _token_to_csv(token: object) -> str:
    """Serialize a condition or AF token to its CSV string."""
    if isinstance(token, (Contact, Coil, CompareContact, Timer, RawInstruction)):
        return token.to_csv()
    if isinstance(token, UnknownCondition):
        raise WriterError(f"Cannot serialize unknown condition to CSV (raw {len(token.raw)} bytes)")
    if isinstance(token, UnknownInstruction):
        raise WriterError(
            f"Cannot serialize unknown instruction to CSV (raw {len(token.raw)} bytes)"
        )
    # Wire tokens and plain strings ("", "-", "|", "T", "+", "+|", "-!", "-|", "NOP")
    return str(token)


# ---------------------------------------------------------------------------
# Rung → CSV rows
# ---------------------------------------------------------------------------


def _is_blank_row(conditions: list[object], af: object) -> bool:
    """Return True if all conditions are blank/empty and AF is blank."""
    if af != "":
        return False
    return all(c == "" for c in conditions)


def decoded_rung_to_rows(rung: DecodedRung) -> list[list[str]]:
    """Convert a ``DecodedRung`` to a list of CSV row lists.

    Each returned row is a list of 33 strings: [marker, A..AE, AF].
    Comment rows have marker ``"#"`` and text in column A.
    Data rows have marker ``"R"`` (first) or ``""`` (continuation).

    Retained timers produce a ``.reset()`` pin row from the second
    grid row.  Non-retained timers strip trailing blank padding.
    """
    rows: list[list[str]] = []

    # --- Comment rows ---
    if rung.comment is not None:
        for line in rung.comment.split("\n"):
            rows.append(["#", line] + [""] * 31)

    # --- Determine timer retention / tall padding ---
    af0 = rung.af_tokens[0] if rung.af_tokens else None
    is_retained_timer = isinstance(af0, Timer) and af0.retained
    is_tall_timer = isinstance(af0, Timer)

    # Build working copies for potential stripping.
    condition_rows = list(rung.condition_rows)
    af_tokens = list(rung.af_tokens)

    if is_retained_timer:
        # Retained timer: the second row becomes a .reset() pin row.
        # Keep all rows — the second row carries reset-enable conditions.
        pass
    elif is_tall_timer:
        # Non-retained tall timer: strip trailing blank padding rows.
        while len(condition_rows) > 1 and _is_blank_row(condition_rows[-1], af_tokens[-1]):
            condition_rows = condition_rows[:-1]
            af_tokens = af_tokens[:-1]

    # --- Data rows ---
    for i, (conditions, af) in enumerate(zip(condition_rows, af_tokens, strict=True)):
        marker = "R" if i == 0 else ""

        # Pin row: retained timer's second row gets .reset() as AF.
        if is_retained_timer and i == 1:
            af_str = ".reset()"
        else:
            af_str = _token_to_csv(af)

        cond_strs = [_token_to_csv(c) for c in conditions]
        rows.append([marker] + cond_strs + [af_str])

    return rows


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def write_decoded_csv(
    path: Path | str,
    rungs: list[DecodedRung],
) -> None:
    """Write decoded rungs to a canonical CSV file.

    Parameters
    ----------
    path:
        Output file path.
    rungs:
        One or more decoded rungs (from ``decode_rung()`` or
        ``decode_multi_rung()``).

    Raises
    ------
    WriterError
        If any rung contains unknown instructions that cannot be serialized.
    """
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(CSV_HEADER)
        for rung in rungs:
            for row in decoded_rung_to_rows(rung):
                writer.writerow(row)


def decode_to_csv(data: bytes, path: Path | str) -> list[DecodedRung]:
    """Decode a Click clipboard binary and write the result as CSV.

    Auto-detects single vs. multi-rung buffers.

    Parameters
    ----------
    data:
        Raw clipboard bytes.
    path:
        Output CSV file path.

    Returns
    -------
    list[DecodedRung]
        The decoded rungs (useful for inspection or further processing).

    Raises
    ------
    WriterError
        If the binary contains unknown instructions.
    """
    try:
        rungs = [decode_rung(data)]
    except Exception:
        rungs = decode_multi_rung(data)

    write_decoded_csv(path, rungs)
    return rungs
