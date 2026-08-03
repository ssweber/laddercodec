"""Inspect decoded ladder rungs from native .bin captures.

Decodes all rungs and prints structured information:
- Known instructions (Contact, Coil, Timer, CompareContact): model repr + to_csv()
- RawInstruction: class name + tagged field breakdown
- UnknownCondition / UnknownInstruction: tagged field breakdown
- Multi-rung support

Usage::

    uv run devtools/inspect_bin.py <file.bin> [file2.bin ...]
"""

import struct
import sys
from pathlib import Path

from laddercodec import decode
from laddercodec.binary_helpers import _parse_tagged_fields_verbose, _read_utf16le
from laddercodec.decode import Rung
from laddercodec.instructions import (
    AfInstruction,
    ConditionInstruction,
    RawInstruction,
    UnknownCondition,
    UnknownInstruction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col_letter(col_idx: int) -> str:
    """Convert 0-based column index to A..AE."""
    if col_idx < 26:
        return chr(ord("A") + col_idx)
    return f"A{chr(ord('A') + col_idx - 26)}"


def _print_blob_detail(raw: bytes, indent: str = "      ") -> None:
    """Print tagged-field breakdown for an instruction blob."""
    class_name, pos = _read_utf16le(raw, 0)
    print(f"{indent}class: {class_name!r}")

    if pos + 4 > len(raw):
        print(f"{indent}(truncated after class name)")
        return

    type_marker = struct.unpack_from("<I", raw, pos)[0]
    print(f"{indent}type_marker: 0x{type_marker:04X}")
    pos += 4

    if pos + 2 > len(raw):
        print(f"{indent}(truncated after type marker)")
        return

    part_count = struct.unpack_from("<H", raw, pos)[0]
    print(f"{indent}part_count: {part_count}")
    pos += 2

    extra = max(0, part_count - 1)
    if extra > 0:
        if pos + extra > len(raw):
            print(f"{indent}(truncated: missing part extra bytes)")
            return
        print(f"{indent}extra_bytes: {raw[pos : pos + extra].hex()}")
        pos += extra

    if pos + 4 > len(raw):
        print(f"{indent}(truncated before field count)")
        return

    field_count = struct.unpack_from("<I", raw, pos)[0]
    print(f"{indent}field_count: {field_count}")
    pos += 4

    fields, pos = _parse_tagged_fields_verbose(raw, pos, field_count)
    for i, (tag, sentinel, value) in enumerate(fields):
        marker = "std" if sentinel == b"\xff\xff\xff\xff" else f"sub={sentinel.hex()}"
        print(f"{indent}field[{i}]: tag=0x{tag:04X} ({marker}) value={value!r}")

    if pos < len(raw):
        print(f"{indent}trailing: {len(raw) - pos} bytes: {raw[pos:].hex(' ')}")


# ---------------------------------------------------------------------------
# Rung display
# ---------------------------------------------------------------------------


def _print_rung(rung: Rung, rung_idx: int) -> None:
    """Print one rung's decoded contents."""
    label = f"  Rung {rung_idx}: {rung.logical_rows} row(s)"
    if rung.comment:
        label += f", comment: {rung.comment!r}"
    print(label)

    for row_idx in range(rung.logical_rows):
        conds = rung.conditions[row_idx]
        af = rung.instructions[row_idx]

        # Collect non-trivial condition tokens (skip blanks and horizontal wires).
        for col_idx, tok in enumerate(conds):
            if tok in ("", "-"):
                continue
            col = _col_letter(col_idx)
            if isinstance(tok, ConditionInstruction):
                print(f"    [{row_idx}][{col}] {tok!r}")
                print(f"      csv: {tok.to_csv()}")
            elif isinstance(tok, UnknownCondition):
                print(f"    [{row_idx}][{col}] UnknownCondition ({len(tok.raw)} bytes)")
                _print_blob_detail(tok.raw)
            else:
                print(f"    [{row_idx}][{col}] {tok!r}")

        if isinstance(af, AfInstruction) and not isinstance(af, RawInstruction):
            print(f"    [{row_idx}][AF] {af!r}")
            print(f"      csv: {af.to_csv()}")
        elif isinstance(af, RawInstruction):
            print(f"    [{row_idx}][AF] RawInstruction class={af.class_name!r}")
            print(f"      csv: {af.to_csv()}")
            _print_blob_detail(af.blob)
        elif isinstance(af, UnknownInstruction):
            print(f"    [{row_idx}][AF] UnknownInstruction ({len(af.raw)} bytes)")
            _print_blob_detail(af.raw)
        elif af == "NOP":
            print(f"    [{row_idx}][AF] NOP")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run devtools/inspect.py <file.bin> [file2.bin ...]")
        sys.exit(1)

    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"--- {path}: NOT FOUND ---")
            continue

        data = path.read_bytes()
        print(f"\n{'=' * 60}")
        print(f"  {path.name} ({len(data)} bytes)")
        print(f"{'=' * 60}")

        result = decode(data)
        if isinstance(result, Rung):
            _print_rung(result, 0)
        else:
            print(f"  Multi-rung: {len(result)} rungs")
            for i, rung in enumerate(result):
                _print_rung(rung, i)


if __name__ == "__main__":
    main()
