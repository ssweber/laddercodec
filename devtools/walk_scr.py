"""Walk SC-SCR temp file using pre-validated instruction sections as anchors.

Phase 1: scan for all valid instruction sections (validated by parsing every blob).
Phase 2: for each section, scan backwards to find its row header and RTF comment.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def parse_blob(data: bytes, pos: int) -> tuple[str, int, int, int, int] | None:
    """Parse instruction blob at pos.

    Returns (class_name, type_code, end_offset, next_pos, row_height) or None.
    """
    if pos >= len(data) - 20:
        return None
    sl = data[pos]
    if not (3 <= sl <= 60 and pos + 1 + sl + 2 <= len(data)):
        return None
    try:
        text = read_utf16le(data, pos + 1, sl)
        type_off = pos + 1 + sl
        marker = struct.unpack_from("<H", data, type_off)[0]
        if not (text and text[0].isupper() and text.isascii() and all(c.isalnum() for c in text)):
            return None
        if not (0x2700 <= marker <= 0x2800):
            return None

        after_type = type_off + 2
        if after_type + 12 > len(data):
            return None
        m1 = data[after_type + 6]
        if not (1 <= m1 <= 8):
            return None
        eo_pos = after_type + 7 + m1
        if eo_pos + 4 > len(data):
            return None
        end_offset = struct.unpack_from("<I", data, eo_pos)[0]
        if not (pos < end_offset < len(data)):
            return None
        next_pos = end_offset + 2
        return text, marker, end_offset, next_pos, m1

    except (UnicodeDecodeError, ValueError, struct.error):
        return None


def find_valid_sections(data: bytes, start: int = 0x100) -> list[tuple[int, int, int]]:
    """Find all valid instruction sections.

    Returns sorted list of (offset, instr_count, end_pos).
    """
    sections = []
    i = start
    while i < len(data) - 5:
        count = struct.unpack_from("<H", data, i)[0]
        if 1 <= count <= 20 and data[i + 2 : i + 6] == b"\x90\x00\x00\x00":
            cursor = i + 6
            ok = True
            for _ in range(count):
                if cursor + 9 > len(data):
                    ok = False
                    break
                blob = parse_blob(data, cursor + 8)
                if not blob:
                    blob = parse_blob(data, cursor + 9)
                if not blob:
                    ok = False
                    break
                cursor = blob[3]
            if ok:
                sections.append((i, count, cursor))
                i = cursor
                continue
        i += 1
    return sections


def parse_section_blobs(data: bytes, offset: int, count: int) -> list[dict]:
    """Parse all instruction blobs in a validated section."""
    instrs = []
    cursor = offset + 6
    for _ in range(count):
        blob = parse_blob(data, cursor + 8)
        if blob:
            icol = data[cursor + 1]
            cls_name, typ, end_off, next_pos, rh = blob
            instrs.append({"col": col_name(icol), "class": cls_name, "type": typ, "rh": rh})
            cursor = next_pos
        elif blob := parse_blob(data, cursor + 9):
            icol = data[cursor + 2]
            cls_name, typ, end_off, next_pos, rh = blob
            instrs.append({"col": col_name(icol), "class": cls_name, "type": typ, "rh": rh})
            cursor = next_pos
        else:
            break
    return instrs


def extract_rtf_text(data: bytes, offset: int, length: int) -> str:
    body = data[offset : offset + length].decode("cp1252", errors="replace")
    fs = body.find("\\fs20 ")
    par = body.find("\\par ")
    if par == -1:
        par = body.find("\\par}")
    if fs >= 0 and par >= 0:
        return body[fs + 6 : par].replace("\r\n", "").strip()
    return "?"


def col_name(idx: int) -> str:
    if idx < 26:
        return chr(ord("A") + idx)
    elif idx < 31:
        return f"A{chr(ord('A') + idx - 26)}"
    else:
        return "AF"


def find_row_header_before(data: bytes, pos: int, max_lookback: int = 400) -> int | None:
    """Find nearest row header signature [XX XX 03 00 00 01 20 00] before pos."""
    start = max(0, pos - max_lookback)
    for i in range(pos - 8, start - 1, -1):
        if data[i + 2 : i + 8] == b"\x03\x00\x00\x01\x20\x00":
            return i
    return None


def find_rtf_before(data: bytes, pos: int, max_lookback: int = 300) -> tuple[int, int, int] | None:
    """Find nearest RTF comment body before pos.

    Returns (rtf_body_offset, rtf_len, rung_idx_offset) or None.
    The structure before RTF is: [u16 rung_idx] [u32 rtf_len] [RTF body...]
    """
    start = max(0, pos - max_lookback)
    for i in range(pos - 2, start - 1, -1):
        if data[i : i + 6] == b"{\\rtf1":
            # RTF body starts at i. u32 rtf_len is at i-4, u16 rung_idx at i-6.
            if i >= 4:
                rtf_len = struct.unpack_from("<I", data, i - 4)[0]
                if rtf_len > 0 and i + rtf_len <= len(data):
                    return i, rtf_len, i - 6
            # Could also be right after the file header (rung 0 has no rung_idx prefix)
            if i >= 4:
                rtf_len = struct.unpack_from("<I", data, i - 4)[0]
                return i, rtf_len, -1
    return None


def parse_header(data: bytes) -> tuple[str, int, int]:
    """Parse file header, return (program_name, prog_idx, data_start)."""
    prog_idx = struct.unpack_from("<H", data, 0x40)[0]
    name_len = data[0x42]
    name = read_utf16le(data, 0x43, name_len)
    cursor = 0x43 + name_len

    # Skip cols_per_row + extra header fields + column types
    cursor += 2
    while cursor < len(data) - 1 and not (data[cursor] == 0x41 and data[cursor + 1] == 0x00):
        cursor += 2
    while cursor < len(data) - 1 and data[cursor] == 0x41 and data[cursor + 1] == 0x00:
        cursor += 2

    # Handle 0x90 prefix
    if data[cursor] == 0x90 and data[cursor + 1] == 0x00:
        cursor += 7  # 2 (marker) + 1 (mystery) + 4 (u32)

    return name, prog_idx, cursor


def walk(path: str, verbose: bool = False) -> None:
    data = Path(path).read_bytes()
    print(f"File: {Path(path).name} ({len(data)} bytes)")

    name, prog_idx, data_start = parse_header(data)
    print(f"Program: {name!r} (idx={prog_idx})")

    # --- Phase 1: find all valid instruction sections ---
    sections = find_valid_sections(data, start=data_start)
    if verbose:
        print(f"  Pre-validated {len(sections)} instruction sections")

    # --- Phase 2: for each section, find its row header and comment ---
    rungs = []
    prev_sec_end = data_start

    for sec_idx, (sec_off, count, sec_end) in enumerate(sections):
        rung = {"comment": None, "rows": 1, "instructions": [], "headerless": False}

        # Find row header between previous section end and this section
        rh = find_row_header_before(data, sec_off)
        if rh is not None and rh >= prev_sec_end:
            row_word = struct.unpack_from("<H", data, rh)[0]
            rung["rows"] = row_word - 1

            # Find RTF comment between prev_sec_end and row header
            rtf = find_rtf_before(data, rh, max_lookback=rh - prev_sec_end + 10)
            if rtf:
                rtf_body_off, rtf_len, _ = rtf
                if rtf_body_off >= prev_sec_end:
                    rung["comment"] = extract_rtf_text(data, rtf_body_off, rtf_len)
        else:
            rung["headerless"] = True
            # Headerless — check for RTF comment just before the section
            rtf = find_rtf_before(data, sec_off, max_lookback=sec_off - prev_sec_end + 10)
            if rtf:
                rtf_body_off, rtf_len, _ = rtf
                if rtf_body_off >= prev_sec_end:
                    rung["comment"] = extract_rtf_text(data, rtf_body_off, rtf_len)

        # Parse instruction blobs
        rung["instructions"] = parse_section_blobs(data, sec_off, count)

        if verbose:
            rh_str = f"rh={rh:#06x}" if rh and rh >= prev_sec_end else "headerless"
            print(
                f"  Section {sec_idx}: {sec_off:#06x} {rh_str} rows={rung['rows']} instrs={len(rung['instructions'])}"
            )

        rungs.append(rung)
        prev_sec_end = sec_end

    # --- Check for terminal sentinel (row header with no section after last section) ---
    last_sec_end = sections[-1][2] if sections else data_start
    for i in range(last_sec_end, len(data) - 7):
        if data[i + 2 : i + 8] == b"\x03\x00\x00\x01\x20\x00":
            row_word = struct.unpack_from("<H", data, i)[0]
            sentinel = {
                "comment": None,
                "rows": row_word - 1,
                "instructions": [],
                "headerless": False,
            }
            # Check for comment before sentinel
            rtf = find_rtf_before(data, i, max_lookback=i - last_sec_end + 10)
            if rtf:
                rtf_body_off, rtf_len, _ = rtf
                if rtf_body_off >= last_sec_end:
                    sentinel["comment"] = extract_rtf_text(data, rtf_body_off, rtf_len)
            rungs.append(sentinel)
            break

    # --- Print results ---
    total_instrs = sum(len(r["instructions"]) for r in rungs)
    print(f"\n{'=' * 72}")
    print(f"DECODED {len(rungs)} RUNGS  ({total_instrs} instructions)")
    print(f"{'=' * 72}")
    for idx, r in enumerate(rungs):
        hdr = "!" if r.get("headerless") else " "
        cmt = r["comment"][:50] if r["comment"] else "(none)"
        instrs = ", ".join(f"{i['col']}:{i['class']}" for i in r["instructions"])
        print(f"  {hdr} Rung {idx:3d}: rows={r['rows']} cmt={cmt!r:52s} instrs=[{instrs}]")


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    path = [a for a in sys.argv[1:] if not a.startswith("-")]
    walk(path[0] if path else r"C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr2.tmp", verbose)
