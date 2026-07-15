from __future__ import annotations

import importlib
import struct
from pathlib import Path

import pytest

from laddercodec import decode
from laddercodec.csv import read_csv
from laddercodec.decode import inspect_cells
from laddercodec.decode_program import (
    _parse_header,
    _parse_row_block,
    _parse_scr_tags,
    _parse_section_entries,
    _parse_wiredown_table,
    _tag_wire_type,
    _walk_rung_records,
    decode_program,
)
from laddercodec.instructions import from_tags_af
from laddercodec.instructions.home import from_tags as home_from_tags
from laddercodec.instructions.math import Math
from laddercodec.instructions.position import from_tags as position_from_tags
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts
from laddercodec.instructions.timer import Timer

decode_program_module = importlib.import_module("laddercodec.decode_program")
_SCR_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"
_COL_NAMES = {
    idx: chr(ord("A") + idx) if idx < 26 else f"A{chr(ord('A') + idx - 26)}" if idx < 31 else "AF"
    for idx in range(32)
}
_COL_IDX_BY_NAME = {name: idx for idx, name in _COL_NAMES.items()}


def _topology_blocks_by_section(
    scr_data: bytes,
) -> dict[int, object]:
    """Map section index (nth rung with instructions) to its topology block."""
    _name, prog_idx, data_start = _parse_header(scr_data)
    records = _walk_rung_records(scr_data, prog_idx, data_start)
    return {idx: record.topology for idx, record in enumerate(r for r in records if r.instructions)}


def _load_fixture_pair(name: str):
    scr_data = (_SCR_FIXTURE_DIR / f"{name}.scr").read_bytes()
    clip_data = (_SCR_FIXTURE_DIR / f"{name}.bin").read_bytes()

    clip_result = decode(clip_data)
    clip_rungs = clip_result if isinstance(clip_result, list) else [clip_result]
    program = decode_program(scr_data)
    return clip_rungs, program.rungs


def _token_to_str(tok) -> str:
    if isinstance(tok, str):
        return tok
    if hasattr(tok, "to_csv"):
        return tok.to_csv()
    return repr(tok)


def _rung_to_lines(rung) -> list[str]:
    return [
        ",".join(_token_to_str(tok) for tok in rung.conditions[row_idx])
        + "|"
        + _token_to_str(rung.instructions[row_idx])
        for row_idx in range(rung.logical_rows)
    ]


def _right_wire_columns(rung, row_idx: int) -> list[int]:
    right_columns: list[int] = []
    for col_idx, tok in enumerate(rung.conditions[row_idx]):
        if tok == "":
            continue
        if isinstance(tok, str):
            if tok in ("-", "T"):
                right_columns.append(col_idx)
            continue
        right_columns.append(col_idx)

    af = rung.instructions[row_idx]
    if af != "":
        right_columns.append(31)

    return right_columns


def _row_block_details(data: bytes, block) -> list[tuple[int, list[tuple[int, int]]]]:
    """Re-parse a topology block's row blocks as (flag, [(seg, col), ...]).

    Preserves the native serialized entry order, unlike the set-based parser.
    """
    pos = block.start + 5
    details: list[tuple[int, list[tuple[int, int]]]] = []
    for _ in range(block.row_word - 1):
        flag = data[pos]
        count = data[pos + 1]
        assert data[pos + 2] == 0
        pos += 3
        entries = [(data[pos + i * 2], data[pos + i * 2 + 1]) for i in range(count)]
        pos += count * 2
        details.append((flag, entries))
    assert data[pos : pos + 2] == b"\x20\x00"
    return details


def _compact_scr_blob(
    class_name: str,
    type_code: int,
    visual_sub_rows: int,
    body: bytes,
) -> bytes:
    class_bytes = class_name.encode("utf-16-le") + b"\x00"
    header = bytearray()
    header.append(len(class_bytes))
    header += class_bytes
    header += type_code.to_bytes(2, "little")
    header += b"\x00" * 6
    header += b"\x01"
    header += b"\x00" * visual_sub_rows
    end_offset = 1 + len(class_bytes) + 2 + 6 + 1 + visual_sub_rows + 4 + len(body)
    header += end_offset.to_bytes(4, "little")
    return bytes(header) + body


def _rebase_compact_scr_blob(blob: bytes, blob_start: int, visual_sub_rows: int) -> bytes:
    """Rewrite end_offset to be relative to blob_start (visual_sub_rows == part_count in clipboard)."""
    rebased = bytearray(blob)
    str_len = rebased[0]
    end_offset_pos = 1 + str_len + 2 + 6 + 1 + visual_sub_rows
    struct.pack_into("<I", rebased, end_offset_pos, blob_start + len(blob))
    return bytes(rebased)


def _compact_scr_string_field(tag: int, value: str) -> bytes:
    encoded = value.encode("utf-16-le") + b"\x00"
    return tag.to_bytes(2, "little") + bytes([len(encoded)]) + encoded


def _compact_scr_byte_field(tag: int, value: int) -> bytes:
    return tag.to_bytes(2, "little") + bytes([value])


def _compact_scr_flag_field(tag: int) -> bytes:
    return tag.to_bytes(2, "little")


def _compact_scr_u16_field(tag: int, value: int) -> bytes:
    return tag.to_bytes(2, "little") + value.to_bytes(2, "little")


def _compact_scr_variant_u16_field(tag: int, entries: dict[int, int]) -> bytes:
    out = bytearray(tag.to_bytes(2, "little"))
    for sub_idx, value in entries.items():
        out += sub_idx.to_bytes(2, "little")
        out += value.to_bytes(2, "little")
    out += (0xFFFF).to_bytes(2, "little")
    return bytes(out)


def _section_instruction_from_token(row: int, col: int, token) -> tuple:
    blob = token.build_blob()
    class_name, type_code, part_count, _extra_bytes, fields = _decompose_blob(blob)
    tags, tag_byte_lens, variant_u16_tags, variant_string_tags = _fields_to_tag_dicts(fields)
    return (
        row,
        col,
        class_name,
        type_code,
        tags,
        part_count,
        tag_byte_lens,
        variant_u16_tags,
        variant_string_tags,
    )


def test_decode_program_matches_or_topology_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("or_topology")

    assert len(scr_rungs) == len(clip_rungs)
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_parse_scr_tags_handles_compact_math_nickname_flag():
    raw = _compact_scr_blob(
        "Math",
        0x271A,
        1,
        b"".join(
            [
                _compact_scr_string_field(0x6065, "DS124"),
                _compact_scr_string_field(0x61FF, "@ + 200"),
                _compact_scr_string_field(0x6228, "<z_AckAndClearAllAlm_loop> + 200"),
                _compact_scr_string_field(0x6229, "@#+#H200"),
                _compact_scr_string_field(0x61FD, "DS123#+#H200"),
                _compact_scr_byte_field(0x2224, 1),
                (0x6888).to_bytes(2, "little"),
            ]
        ),
    )

    class_name, type_code, tags, tag_byte_lens, variant_u16_tags, variant_string_tags = (
        _parse_scr_tags(
            raw,
            0,
            len(raw),
            1,
        )
    )
    parsed = from_tags_af(
        class_name,
        type_code,
        tags,
        tag_byte_lens,
        variant_u16_tags,
        variant_string_tags,
    )

    assert parsed == Math(expression="DS123 + 200", result="DS124", mode="decimal", oneshot=False)


def test_parse_scr_tags_handles_compact_timer_variant_fields():
    raw = _compact_scr_blob(
        "Tmr",
        0x2718,
        2,
        b"".join(
            [
                _compact_scr_string_field(0x6068, "T141"),
                _compact_scr_string_field(0x606A, "DS588"),
                _compact_scr_string_field(0x6069, "TD141"),
                _compact_scr_byte_field(0x21F9, 1),
                _compact_scr_byte_field(0x21FB, 1),
                _compact_scr_variant_u16_field(0x3A05, {0: 8725, 1: 8726}),
                (0x0000).to_bytes(2, "little"),
            ]
        ),
    )

    class_name, type_code, tags, tag_byte_lens, variant_u16_tags, variant_string_tags = (
        _parse_scr_tags(
            raw,
            0,
            len(raw),
            2,
        )
    )
    parsed = from_tags_af(
        class_name,
        type_code,
        tags,
        tag_byte_lens,
        variant_u16_tags,
        variant_string_tags,
    )

    assert parsed == Timer(
        timer_type="on_delay",
        done_bit="T141",
        current="TD141",
        setpoint="DS588",
        unit="Ts",
        retained=True,
    )


def test_parse_section_entries_accepts_large_instruction_counts():
    blobs: list[bytes] = []
    for idx in range(21):
        raw_blob = _compact_scr_blob(
            "ContactNO",
            0x2711,
            1,
            _compact_scr_string_field(0x6065, f"C{idx + 1}") + (0x0000).to_bytes(2, "little"),
        )
        entry_start = 6 + sum(len(existing) for existing in blobs)
        blob = _rebase_compact_scr_blob(raw_blob, entry_start + 8, 1)
        blobs.append(bytes([1, idx % 31]) + b"\x00" * 6 + blob + b"\x00\x00")

    section = struct.pack("<H", len(blobs)) + struct.pack("<I", 1) + b"".join(blobs)
    parsed = _parse_section_entries(section, 6, 21, len(section))
    assert parsed is not None
    instructions, end_pos = parsed
    assert end_pos == len(section)
    assert [(row, col, name) for row, col, name, *_ in instructions] == [
        (0, idx % 31, "ContactNO") for idx in range(21)
    ]


def test_parse_wiredown_table_uses_explicit_row_indices():
    data = b"\x00\x00" + b"\x05\x00\x02\x03\x04\x05\x06" + b"\x00\x00" * 30
    assert _parse_wiredown_table(data, 0, len(data)) == ({1: (1, 2, 3, 4, 5)}, len(data))


def test_parse_wiredown_table_requires_all_32_columns():
    data = b"\x00\x00" * 31  # one column entry short
    assert _parse_wiredown_table(data, 0, len(data)) is None


def test_parse_row_block_accepts_seg1_first_entry():
    # AlmHistorian regression: a continuation row whose first right-wired cell
    # carries segment flag 1 (`00 01 00 | 01 00` = flag=0, count=1, entry
    # seg=1 col=0).  The old framing demanded `00 00` after the count and
    # rejected the whole topology block, silently dropping the rung's wires.
    data = bytes.fromhex("0001000100")
    assert _parse_row_block(data, 0, len(data)) == ({0}, True, 5)


def test_parse_row_block_empty_row():
    data = bytes.fromhex("010000")
    assert _parse_row_block(data, 0, len(data)) == (set(), False, 3)


def test_parse_row_block_row0_signature():
    # col 0 present + all condition segs 1 (col-31 seg exempt) = grid row 0;
    # a seg-0 condition cell breaks the signature.
    data = bytes.fromhex("01 03 00 01 00 01 01 01 1f")
    assert _parse_row_block(data, 0, len(data)) == ({0, 1, 31}, True, 9)

    data = bytes.fromhex("01 03 00 01 00 00 01 01 1f")
    assert _parse_row_block(data, 0, len(data)) == ({0, 1, 31}, False, 9)


def test_parse_scr_tags_handles_compact_home_raw_fields():
    raw = _compact_scr_blob(
        "Home",
        0x2734,
        1,
        b"".join(
            [
                _compact_scr_byte_field(0x222D, 1),
                _compact_scr_byte_field(0x222E, 1),
                _compact_scr_string_field(0x6096, "DD101"),
                _compact_scr_string_field(0x6097, ""),
                _compact_scr_string_field(0x609E, ""),
                _compact_scr_string_field(0x609F, "X003"),
                _compact_scr_string_field(0x60A0, ""),
                _compact_scr_string_field(0x609C, "DD102"),
                _compact_scr_string_field(0x609D, "DD103"),
                _compact_scr_byte_field(0x222F, 0),
                _compact_scr_flag_field(0x11F5),
                _compact_scr_byte_field(0x2230, 255),
                _compact_scr_string_field(0x60A1, "0"),
                _compact_scr_string_field(0x60A3, "C102"),
                _compact_scr_string_field(0x60A4, ""),
                _compact_scr_string_field(0x607B, "C103"),
                _compact_scr_string_field(0x607D, ""),
                _compact_scr_string_field(0x6083, ""),
                _compact_scr_byte_field(0x2232, 0),
                _compact_scr_byte_field(0x2233, 0),
                _compact_scr_u16_field(0x3218, 9739),
                (0x0000).to_bytes(2, "little"),
            ]
        ),
    )

    class_name, type_code, tags, _tbl, _v_u16, _v_str = _parse_scr_tags(
        raw,
        0,
        len(raw),
        1,
    )
    parsed = home_from_tags(class_name, type_code, tags)

    assert parsed is not None
    assert (
        parsed.to_csv() == "raw(Home,0x2734,1,222d=1,222e=1,6096=DD101,6097=,609e=,609f=X003,60a0=,"
        "609c=DD102,609d=DD103,222f=0,11f5=0,2230=255,60a1=0,60a3=C102,60a4=,607b=C103,"
        "607d=,6083=,2232=0,2233=0,3218=9739,0000=)"
    )


def test_parse_scr_tags_handles_compact_position_raw_fields():
    raw = _compact_scr_blob(
        "Position",
        0x2736,
        1,
        b"".join(
            [
                _compact_scr_byte_field(0x222D, 2),
                _compact_scr_string_field(0x6098, "DD301"),
                _compact_scr_string_field(0x6099, ""),
                _compact_scr_string_field(0x609A, "DD304"),
                _compact_scr_byte_field(0x2206, 0),
                _compact_scr_string_field(0x609B, "DD119"),
                _compact_scr_string_field(0x609C, "DD120"),
                _compact_scr_string_field(0x609D, "DD121"),
                _compact_scr_byte_field(0x222F, 2),
                _compact_scr_flag_field(0x11F5),
                _compact_scr_byte_field(0x2231, 0),
                _compact_scr_string_field(0x60A2, ""),
                _compact_scr_string_field(0x60A3, "C315"),
                _compact_scr_string_field(0x60A4, ""),
                _compact_scr_string_field(0x607B, "C316"),
                _compact_scr_string_field(0x607D, ""),
                _compact_scr_string_field(0x6083, ""),
                _compact_scr_u16_field(0x3218, 9745),
                (0x0000).to_bytes(2, "little"),
            ]
        ),
    )

    class_name, type_code, tags, _tbl, _v_u16, _v_str = _parse_scr_tags(
        raw,
        0,
        len(raw),
        1,
    )
    parsed = position_from_tags(class_name, type_code, tags)

    assert parsed is not None
    assert (
        parsed.to_csv()
        == "raw(Position,0x2736,1,222d=2,6098=DD301,6099=,609a=DD304,2206=0,609b=DD119,"
        "609c=DD120,609d=DD121,222f=2,11f5=0,2231=0,60a2=,60a3=C315,60a4=,607b=C316,"
        "607d=,6083=,3218=9745,0000=)"
    )


def test_topology_row_blocks_match_or_topology_clipboard_columns():
    scr_data = (_SCR_FIXTURE_DIR / "or_topology.scr").read_bytes()
    clip_data = (_SCR_FIXTURE_DIR / "or_topology.bin").read_bytes()

    clip_result = decode(clip_data)
    clip_rungs = clip_result if isinstance(clip_result, list) else [clip_result]

    topo_map = _topology_blocks_by_section(scr_data)

    for rung_idx, clip_rung in enumerate(clip_rungs):
        if clip_rung.logical_rows < 2:
            continue

        block = topo_map.get(rung_idx)
        assert block is not None
        assert len(block.rows_right_cols) == clip_rung.logical_rows

        expected = [
            sorted(_right_wire_columns(clip_rung, row_idx))
            for row_idx in range(clip_rung.logical_rows)
        ]
        actual = [sorted(cols) for cols in block.rows_right_cols]

        assert actual == expected


def test_row_block_seg_flags_match_clipboard_segment_flags():
    scr_data = (_SCR_FIXTURE_DIR / "or_topology.scr").read_bytes()
    clip_data = (_SCR_FIXTURE_DIR / "or_topology.bin").read_bytes()

    clip_result = decode(clip_data)
    clip_rungs = clip_result if isinstance(clip_result, list) else [clip_result]

    topo_map = _topology_blocks_by_section(scr_data)

    saw_wrapped_order = False

    for rung_idx, clip_rung in enumerate(clip_rungs):
        if clip_rung.logical_rows < 2:
            continue

        block = topo_map.get(rung_idx)
        assert block is not None

        for row_idx, (_flag, entries) in enumerate(_row_block_details(scr_data, block)):
            ordered_columns = [col for _seg, col in entries]
            expected_columns = _right_wire_columns(clip_rung, row_idx)
            assert set(ordered_columns) == set(expected_columns)

            if not entries:
                continue

            if ordered_columns != sorted(ordered_columns):
                saw_wrapped_order = True

            cell_dumps = inspect_cells(
                clip_data,
                [(rung_idx, row_idx, _COL_NAMES[col_idx]) for col_idx in ordered_columns],
            )
            seg_by_col = {_COL_IDX_BY_NAME[cell.col]: cell.flags[0] for cell in cell_dumps}

            # Each entry's seg byte is that cell's own +0x19 segment flag.
            for seg, col in entries:
                assert seg == seg_by_col[col]

    assert saw_wrapped_order


def test_decode_program_matches_coverage_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("coverage")

    assert len(clip_rungs) == 114
    assert len(scr_rungs) == 114
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def _strip_blank_tail(lines: list[str]) -> list[str]:
    """Remove trailing all-blank rows (CSV writer collapses spacer padding)."""
    blank = "," * 30 + "|"
    while lines and lines[-1] == blank:
        lines = lines[:-1]
    return lines


def test_coverage_scr_and_bin_both_match_golden_csv():
    csv_rungs = read_csv(_SCR_FIXTURE_DIR / "coverage.csv")
    clip_rungs, scr_rungs = _load_fixture_pair("coverage")

    csv_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in csv_rungs]
    scr_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in scr_rungs]
    bin_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in clip_rungs]

    assert scr_lines == csv_lines
    assert bin_lines == csv_lines


def test_decode_program_matches_shift_scr_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("shift_scr")

    assert len(scr_rungs) == len(clip_rungs) == 2
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_decode_program_matches_counter_scr_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("counter_scr")

    assert len(scr_rungs) == len(clip_rungs)
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_time_drums_scr_and_bin_both_match_golden_csv():
    """Time drums across all units + jog/jump, a T-wire branch, and a drum
    carrying a stray pin-row NOP: SCR, clipboard, and golden CSV all agree."""
    csv_rungs = read_csv(_SCR_FIXTURE_DIR / "time_drums.csv")
    clip_rungs, scr_rungs = _load_fixture_pair("time_drums")

    csv_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in csv_rungs]
    scr_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in scr_rungs]
    bin_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in clip_rungs]

    assert len(scr_rungs) == 15
    assert scr_lines == csv_lines
    assert bin_lines == csv_lines


def test_time_drums_scr_drops_stray_pin_row_nop():
    """The drum built with a stranded reset-row NOP decodes to drum + T-wire +
    .reset() pin, with the stray NOP dropped rather than surfaced."""
    from laddercodec.instructions import Drum

    _clip, scr_rungs = _load_fixture_pair("time_drums")
    rung = scr_rungs[14]
    assert isinstance(rung.instructions[0], Drum)
    assert rung.conditions[0][1] == "T"  # column B branch wire preserved
    assert "NOP" not in rung.instructions  # stray editing-cruft NOP dropped


def test_parse_header_skips_fixed_condition_family_table_without_a_sentinel():
    scr_data = bytearray(b"\x00" * 0xC0)
    scr_data[:8] = b"SC-SCR  "
    struct.pack_into("<H", scr_data, 0x40, 1)

    name_bytes = "Main Program".encode("utf-16-le") + b"\x00"
    scr_data[0x42] = len(name_bytes)
    scr_data[0x43 : 0x43 + len(name_bytes)] = name_bytes

    cursor = 0x43 + len(name_bytes)
    struct.pack_into("<H", scr_data, cursor, 32)
    cursor += 2
    for family_code in ["~", *["H"] * 30]:
        struct.pack_into("<H", scr_data, cursor, ord(family_code))
        cursor += 2

    rtf = b"{\\rtf1 synthetic}"
    scr_data[cursor : cursor + 7] = bytes.fromhex("9a010d08000000")
    struct.pack_into("<I", scr_data, cursor + 7, len(rtf))
    scr_data[cursor + 11 : cursor + 11 + len(rtf)] = rtf

    assert _parse_header(bytes(scr_data)) == ("Main Program", 1, cursor + 7)


def _synthetic_rtf(text: str) -> bytes:
    return (
        b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
        b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
        b"\\viewkind4\\uc1\\pard\\fs20 " + text.encode("ascii") + b"\r\n\\par }\r\n"
    )


def _synthetic_scr(rung_comments: list[str | None]) -> bytes:
    """Build a minimal subroutine SCR of empty rungs with the given comments."""
    buf = bytearray(b"SC-SCR  ")
    buf += b"\x00" * (0x40 - len(buf))
    buf += struct.pack("<H", 2)  # prog_idx (subroutine: no file tail)
    name_bytes = "Synth".encode("utf-16-le") + b"\x00"
    buf.append(len(name_bytes))
    buf += name_bytes
    buf += struct.pack("<H", 32)  # cols_per_row
    buf += struct.pack("<H", ord("H")) * 31  # condition-family table

    # Rung-0 file prelude: [u16 file_marker][0d][u32 total rung records]
    buf += struct.pack("<H", 144) + b"\x0d" + struct.pack("<I", len(rung_comments))

    for index, comment in enumerate(rung_comments):
        if index > 0:
            buf += struct.pack("<H", index)
        rtf = _synthetic_rtf(comment) if comment is not None else b""
        buf += struct.pack("<I", len(rtf)) + rtf
        # Topology: row_word=2, one empty row block, end marker, 32-col wiredown
        buf += struct.pack("<H", 2) + b"\x03\x00\x00" + b"\x01\x00\x00"
        buf += b"\x20\x00" + b"\x00" * 64
        buf += b"\x00\x00"  # instr_count = 0 (empty rung)
    return bytes(buf)


def test_decode_program_keeps_comments_for_consecutive_empty_rungs():
    data = _synthetic_scr(["first", "second", "third", None])

    program = decode_program(data)

    # The trailing comment-less record is a placeholder and is dropped; the
    # commented empty rungs are real and keep their own comments.
    assert program.name == "Synth"
    assert [r.comment for r in program.rungs] == ["first", "second", "third"]
    assert all(r.logical_rows == 1 for r in program.rungs)


def test_decode_program_rejects_corrupt_rung_index():
    data = bytearray(_synthetic_scr(["first", None, None]))
    # Corrupt the second rung's index word (locate it: first rung record ends
    # after its 00 00 count; the next two bytes are the u16 index == 1).
    idx_pos = data.index(struct.pack("<H", 1) + b"\x00\x00\x00\x00\x02\x00\x03\x00\x00")
    struct.pack_into("<H", data, idx_pos, 9)

    with pytest.raises(ValueError, match="rung index mismatch"):
        decode_program(bytes(data))


def test_topology_row_blocks_match_coverage_clipboard_columns():
    scr_data = (_SCR_FIXTURE_DIR / "coverage.scr").read_bytes()
    clip_rungs, _scr_rungs = _load_fixture_pair("coverage")

    topo_map = _topology_blocks_by_section(scr_data)

    # Rungs whose row-0 block has 31 entries (col A occupied, no AF wire).
    for rung_idx in [58, 70, 71, 72, 75, 76]:
        block = topo_map.get(rung_idx)
        assert block is not None
        assert len(block.rows_right_cols[0]) == 31
        assert len(block.rows_right_cols) == clip_rungs[rung_idx].logical_rows

        expected_rows = [
            sorted(_right_wire_columns(clip_rungs[rung_idx], row_idx))
            for row_idx in range(1, clip_rungs[rung_idx].logical_rows)
        ]
        actual_rows = [sorted(cols) for cols in block.rows_right_cols[1:]]
        assert actual_rows == expected_rows


def test_count_down_topology_blocks_use_uniform_row_blocks():
    """count_down counter rungs need no special-casing: their stored row
    blocks map 1:1 to grid rows (AF row simply carries flag=0)."""
    scr_data = (_SCR_FIXTURE_DIR / "counter_scr.scr").read_bytes()

    topo_map = _topology_blocks_by_section(scr_data)

    for rung_idx, expected_start, expected_rows in (
        (2, None, [set(), set(range(32)), set()]),
        (3, None, [set(), set(range(32)), set(range(31))]),
        (6, 0xA58, [set(range(7)), set(range(7, 32)), set(range(31))]),
        (7, 0xC93, [set(range(7)), set(range(7)), set(range(7, 32)), set(range(31))]),
    ):
        block = topo_map.get(rung_idx)
        assert block is not None
        if expected_start is not None:
            assert block.start == expected_start
        assert block.row_word == len(expected_rows) + 1
        assert [set(cols) for cols in block.rows_right_cols] == expected_rows


def test_topology_row_block_entries_can_use_wrapped_order():
    """Entry order is placement-ordered, not ascending: these native captures
    store row-0 columns as [6,1,0,3,2,4,5] and [1..31,0]."""
    counter_data = (_SCR_FIXTURE_DIR / "counter_scr.scr").read_bytes()
    counter_map = _topology_blocks_by_section(counter_data)
    block = counter_map[6]
    _flag, entries = _row_block_details(counter_data, block)[0]
    assert [col for _seg, col in entries] == [6, 1, 0, 3, 2, 4, 5]

    coverage_data = (_SCR_FIXTURE_DIR / "coverage.scr").read_bytes()
    coverage_map = _topology_blocks_by_section(coverage_data)
    for rung_idx, wrapped_row in ((48, 0), (49, 1)):
        block = coverage_map[rung_idx]
        _flag, entries = _row_block_details(coverage_data, block)[wrapped_row]
        assert [col for _seg, col in entries] == [*range(1, 32), 0]


def test_rung_walk_yields_a_topology_block_for_every_section():
    """Every instruction rung must carry a structurally valid topology block."""
    _PREFIX = decode_program_module._ROW_TOPOLOGY_PREFIX

    for scr_path in sorted(_SCR_FIXTURE_DIR.glob("*.scr")):
        scr_data = scr_path.read_bytes()
        topo_map = _topology_blocks_by_section(scr_data)

        for rung_idx, block in topo_map.items():
            pos = block.start
            assert scr_data[pos + 2 : pos + 5] == _PREFIX
            assert len(block.rows_right_cols) == block.row_word - 1, (
                f"{scr_path.name} rung {rung_idx}: row block count mismatch"
            )


def test_tag_wire_type_covers_all_implicit_tags():
    """Every tag constant used via tags.get / in tags / _raw_field must resolve to a known wire type.

    The spec tables only list tags with non-default wire types. String tags
    (0x60xx–0x62xx) are implicit — they work via the default fallback path in
    _parse_scr_tags. This test ensures _tag_wire_type returns something other
    than "unknown" for every tag referenced at a call site, so the dispatch
    refactor won't silently drop them.
    """
    import inspect
    import re

    # Gather source of all from_tags functions in instruction modules
    from laddercodec.instructions import AF_FAMILY_SPECS, CONDITION_FAMILY_SPECS

    source_parts = []
    for spec in (*CONDITION_FAMILY_SPECS, *AF_FAMILY_SPECS):
        if spec.from_tags is not None:
            source_parts.append(inspect.getsource(spec.from_tags))
    source = "\n".join(source_parts)

    # Extract tag constants from various accessor patterns
    tag_pattern = re.compile(
        r"(?:"
        r"tags\.get\(|"
        r"lens\.get\(|"
        r"variant_strings\.get\(|"
        r"variant_u16\.get\(|"
        r"tag_byte_lens\b[^)]*\.get\(|"
        r"_raw_field\(|"
        r"_raw_empty_array_fields\("
        r")(0x[0-9A-Fa-f]{4})"
        r"|"
        r"(0x[0-9A-Fa-f]{4})\s+in\s+tags"
    )
    tag_ids: set[int] = set()
    for m in tag_pattern.finditer(source):
        hex_str = m.group(1) or m.group(2)
        tag_ids.add(int(hex_str, 16))

    # 0x0000 is the null terminator, not a real tag
    tag_ids.discard(0x0000)

    unknowns = sorted(t for t in tag_ids if _tag_wire_type(t) == "unknown")
    assert not unknowns, (
        "Tags used at call sites but _tag_wire_type returns 'unknown':\n"
        + "\n".join(f"  0x{t:04X}" for t in unknowns)
    )
