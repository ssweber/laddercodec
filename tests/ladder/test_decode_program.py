from __future__ import annotations

import importlib
import struct
from pathlib import Path

from laddercodec import decode
from laddercodec.decode import inspect_cells
from laddercodec.decode_program import (
    _SCR_TAG_PARSE_SPECS,
    _find_row_topology_block,
    _find_sections,
    _parse_extra_row_right_wires,
    _parse_header,
    _parse_scr_tags,
    _parse_wiredown,
    _scr_to_af,
    _scr_to_raw_af,
    decode_program,
)
from laddercodec.instructions.math import Math
from laddercodec.instructions.timer import Timer

decode_program_module = importlib.import_module("laddercodec.decode_program")
_SCR_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"
_COL_NAMES = {
    idx: chr(ord("A") + idx) if idx < 26 else f"A{chr(ord('A') + idx - 26)}" if idx < 31 else "AF"
    for idx in range(32)
}
_COL_IDX_BY_NAME = {name: idx for idx, name in _COL_NAMES.items()}


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


def _parse_extra_row_right_wire_detail(
    data: bytes,
    start: int,
) -> tuple[tuple[int, ...], dict[int, int], int]:
    """Return serialized continuation-row columns plus per-entry next_seg values."""
    assert data[start] == 0
    right_count = data[start + 1]
    block_len = right_count * 2 + 3

    if right_count == 0:
        return (), {}, block_len

    body = data[start + 2 : start + block_len]
    assert body[:2] == b"\x00\x00"

    pair_bytes = body[2:-1]
    assert len(pair_bytes) == (right_count - 1) * 2

    ordered_columns: list[int] = []
    next_seg_by_col: dict[int, int] = {}
    for i in range(0, len(pair_bytes), 2):
        col_idx = pair_bytes[i]
        next_seg = pair_bytes[i + 1]
        ordered_columns.append(col_idx)
        next_seg_by_col[col_idx] = next_seg

    ordered_columns.append(body[-1])
    return tuple(ordered_columns), next_seg_by_col, block_len


def _parse_row0_entry_order(data: bytes, block) -> tuple[int, ...]:
    return tuple(data[block.flags_start + i * 2 + 1] for i in range(block.row0_flag_count))


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


def _compact_scr_u16_field(tag: int, value: int) -> bytes:
    return tag.to_bytes(2, "little") + value.to_bytes(2, "little")


def _compact_scr_variant_u16_field(tag: int, entries: dict[int, int]) -> bytes:
    out = bytearray(tag.to_bytes(2, "little"))
    for sub_idx, value in entries.items():
        out += sub_idx.to_bytes(2, "little")
        out += value.to_bytes(2, "little")
    out += (0xFFFF).to_bytes(2, "little")
    return bytes(out)


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
            _SCR_TAG_PARSE_SPECS["Math"],
        )
    )
    parsed = _scr_to_af(
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
            _SCR_TAG_PARSE_SPECS["Tmr"],
        )
    )
    parsed = _scr_to_af(
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


def test_find_sections_accepts_large_instruction_counts():
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
    assert _find_sections(section, start=0) == [(0, 21, len(section))]


def test_parse_wiredown_uses_explicit_row_indices():
    data = b"\x20\x00" + b"\x00\x00" + b"\x05\x00\x02\x03\x04\x05\x06" + b"\x00\x00"
    assert _parse_wiredown(data, 0, len(data)) == {1: (1, 2, 3, 4, 5)}


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
                _compact_scr_byte_field(0x11F5, 0),
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
        _SCR_TAG_PARSE_SPECS["Home"],
    )
    parsed = _scr_to_raw_af(class_name, type_code, tags, 1)

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
                _compact_scr_byte_field(0x11F5, 0),
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
        _SCR_TAG_PARSE_SPECS["Position"],
    )
    parsed = _scr_to_raw_af(class_name, type_code, tags, 1)

    assert parsed is not None
    assert (
        parsed.to_csv()
        == "raw(Position,0x2736,1,222d=2,6098=DD301,6099=,609a=DD304,2206=0,609b=DD119,"
        "609c=DD120,609d=DD121,222f=2,11f5=0,2231=0,60a2=,60a3=C315,60a4=,607b=C316,"
        "607d=,6083=,3218=9745,0000=)"
    )


def test_parse_extra_row_right_wires_matches_or_topology_clipboard_columns():
    scr_data = (_SCR_FIXTURE_DIR / "or_topology.scr").read_bytes()
    clip_data = (_SCR_FIXTURE_DIR / "or_topology.bin").read_bytes()

    clip_result = decode(clip_data)
    clip_rungs = clip_result if isinstance(clip_result, list) else [clip_result]

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    for rung_idx, clip_rung in enumerate(clip_rungs):
        if clip_rung.logical_rows < 2:
            continue

        sec_off, _count, _sec_end = sections[rung_idx]
        block = _find_row_topology_block(scr_data, sec_off)
        assert block is not None

        extra_rows_right_wires, marker_pos = _parse_extra_row_right_wires(
            scr_data,
            block.continuation_start,
            sec_off,
            clip_rung.logical_rows - 1,
        )

        expected = [
            sorted(_right_wire_columns(clip_rung, row_idx))
            for row_idx in range(1, clip_rung.logical_rows)
        ]
        actual = [sorted(cols) for cols in extra_rows_right_wires]

        assert actual == expected
        assert marker_pos is not None
        assert scr_data[marker_pos : marker_pos + 2] == b"\x20\x00"


def test_continuation_row_next_seg_matches_successor_segment_flags():
    scr_data = (_SCR_FIXTURE_DIR / "or_topology.scr").read_bytes()
    clip_data = (_SCR_FIXTURE_DIR / "or_topology.bin").read_bytes()

    clip_result = decode(clip_data)
    clip_rungs = clip_result if isinstance(clip_result, list) else [clip_result]

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    saw_wrapped_order = False

    for rung_idx, clip_rung in enumerate(clip_rungs):
        if clip_rung.logical_rows < 2:
            continue

        sec_off, _count, _sec_end = sections[rung_idx]
        block = _find_row_topology_block(scr_data, sec_off)
        assert block is not None

        pos = block.continuation_start
        for row_idx in range(1, clip_rung.logical_rows):
            ordered_columns, next_seg_by_col, block_len = _parse_extra_row_right_wire_detail(
                scr_data, pos
            )
            pos += block_len

            expected_columns = tuple(_right_wire_columns(clip_rung, row_idx))
            assert set(ordered_columns) == set(expected_columns)

            if not ordered_columns:
                continue

            if ordered_columns != tuple(sorted(ordered_columns)):
                saw_wrapped_order = True

            cell_dumps = inspect_cells(
                clip_data,
                [(rung_idx, row_idx, _COL_NAMES[col_idx]) for col_idx in ordered_columns],
            )
            seg_by_col = {_COL_IDX_BY_NAME[cell.col]: cell.flags[0] for cell in cell_dumps}

            for current_col, next_col in zip(ordered_columns, ordered_columns[1:], strict=False):
                assert next_seg_by_col[current_col] == seg_by_col[next_col]

    assert saw_wrapped_order


def test_decode_program_matches_coverage_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("coverage")

    assert len(clip_rungs) == 114
    assert len(scr_rungs) == 114
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_decode_program_matches_shift_scr_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("shift_scr")

    assert len(scr_rungs) == len(clip_rungs) == 2
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_decode_program_matches_counter_scr_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("counter_scr")

    assert len(scr_rungs) == len(clip_rungs)
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


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


def test_decode_program_keeps_comments_for_consecutive_empty_topology_rungs(monkeypatch):
    empty_block_1 = decode_program_module._ScrRowTopologyBlock(
        start=20,
        row_word=2,
        prelude=b"",
        leading_rows_right_wires=[],
        row0_flag_count=32,
        row0_flags={},
        flags_start=20,
        continuation_start=20,
    )
    empty_block_2 = decode_program_module._ScrRowTopologyBlock(
        start=50,
        row_word=2,
        prelude=b"",
        leading_rows_right_wires=[],
        row0_flag_count=32,
        row0_flags={},
        flags_start=50,
        continuation_start=50,
    )
    main_block = decode_program_module._ScrRowTopologyBlock(
        start=80,
        row_word=2,
        prelude=b"",
        leading_rows_right_wires=[],
        row0_flag_count=32,
        row0_flags={},
        flags_start=80,
        continuation_start=80,
    )
    comment_calls: list[tuple[int, int]] = []

    monkeypatch.setattr(decode_program_module, "_parse_header", lambda data: ("Main Program", 1, 0))
    monkeypatch.setattr(
        decode_program_module, "_find_sections", lambda data, start: [(100, 1, 110)]
    )
    monkeypatch.setattr(
        decode_program_module,
        "_parse_section_instructions",
        lambda data, sec_off, count: [],
    )
    monkeypatch.setattr(
        decode_program_module,
        "_find_row_topology_block",
        lambda data, pos: main_block,
    )
    monkeypatch.setattr(
        decode_program_module,
        "_find_row_topology_blocks_between",
        lambda data, start, end: [empty_block_1, empty_block_2],
    )

    def fake_find_rtf_comment(data, start, end):
        comment_calls.append((start, end))
        return None, f"comment {start}->{end}"

    monkeypatch.setattr(decode_program_module, "_find_rtf_comment", fake_find_rtf_comment)
    monkeypatch.setattr(
        decode_program_module,
        "_build_topology_backed_rung",
        lambda **kwargs: kwargs["comment"],
    )

    program = decode_program_module.decode_program(b"")

    assert comment_calls == [(0, 20), (20, 50), (50, 80)]
    assert program.rungs == ["comment 0->20", "comment 20->50", "comment 50->80"]


def test_parse_31_entry_row_topology_blocks_in_coverage_fixture():
    scr_data = (_SCR_FIXTURE_DIR / "coverage.scr").read_bytes()
    clip_rungs, _scr_rungs = _load_fixture_pair("coverage")

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    for rung_idx in [58, 70, 71, 72, 75, 76]:
        sec_off, _count, _sec_end = sections[rung_idx]
        block = _find_row_topology_block(scr_data, sec_off)
        assert block is not None
        assert block.row0_flag_count == 31
        assert block.prelude.endswith(b"\x1f\x00")

        raw_rows, marker_pos = _parse_extra_row_right_wires(
            scr_data,
            block.continuation_start,
            sec_off,
            clip_rungs[rung_idx].logical_rows - 1,
        )
        assert marker_pos is not None
        assert len(raw_rows) == clip_rungs[rung_idx].logical_rows - 1

        expected_rows = [
            sorted(_right_wire_columns(clip_rungs[rung_idx], row_idx))
            for row_idx in range(1, clip_rungs[rung_idx].logical_rows)
        ]
        actual_rows = [sorted(cols) for cols in raw_rows]
        assert actual_rows == expected_rows


def test_counter_row_topology_blocks_capture_variable_preludes():
    scr_data = (_SCR_FIXTURE_DIR / "counter_scr.scr").read_bytes()

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    for rung_idx, expected_prelude, expected_rows in (
        (2, bytes.fromhex("0400030000000000012000"), [[]]),
        (3, bytes.fromhex("0400030000010000002000"), [list(range(31))]),
    ):
        sec_off, _count, _sec_end = sections[rung_idx]
        prev_sec_end = sections[rung_idx - 1][2]
        block = _find_row_topology_block(scr_data, sec_off)
        assert block is not None
        assert block.start > prev_sec_end
        assert block.row_word == 4
        assert block.row0_flag_count == 32
        assert block.prelude == expected_prelude

        raw_rows, marker_pos = _parse_extra_row_right_wires(
            scr_data,
            block.continuation_start,
            sec_off,
            2,
        )
        assert marker_pos is not None
        assert [sorted(cols) for cols in raw_rows] == expected_rows


def test_counter_count_down_with_row0_data_uses_local_sparse_topology_block():
    scr_data = (_SCR_FIXTURE_DIR / "counter_scr.scr").read_bytes()

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    rung_idx = 6
    sec_off, _count, _sec_end = sections[rung_idx]
    prev_sec_end = sections[rung_idx - 1][2]
    block = _find_row_topology_block(scr_data, sec_off)

    assert block is not None
    assert block.start == 0xA58
    assert block.start > prev_sec_end
    assert block.row_word == 4
    assert block.prelude == bytes.fromhex("04000300000007000006000100000003000200040005011900")
    assert block.row0_flag_count == 25
    assert _parse_row0_entry_order(scr_data, block) == tuple(range(7, 32))
    assert [sorted(cols) for cols in block.leading_rows_right_wires] == [list(range(7))]

    raw_rows, marker_pos = _parse_extra_row_right_wires(
        scr_data,
        block.continuation_start,
        sec_off,
        2,
    )
    assert marker_pos is not None
    assert [sorted(cols) for cols in raw_rows] == [list(range(31))]


def test_counter_count_down_with_row0_and_row1_data_uses_two_local_sparse_leading_rows():
    scr_data = (_SCR_FIXTURE_DIR / "counter_scr.scr").read_bytes()

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    rung_idx = 7
    sec_off, _count, _sec_end = sections[rung_idx]
    prev_sec_end = sections[rung_idx - 1][2]
    block = _find_row_topology_block(scr_data, sec_off)

    assert block is not None
    assert block.start == 0xC93
    assert block.start > prev_sec_end
    assert block.row_word == 5
    assert block.prelude == bytes.fromhex(
        "050003000000070000000001000200030004000500060107000000000100020003000400050006001900"
    )
    assert block.row0_flag_count == 25
    assert _parse_row0_entry_order(scr_data, block) == tuple(range(7, 32))
    assert [sorted(cols) for cols in block.leading_rows_right_wires] == [
        list(range(7)),
        list(range(7)),
    ]

    raw_rows, marker_pos = _parse_extra_row_right_wires(
        scr_data,
        block.continuation_start,
        sec_off,
        3,
    )
    assert marker_pos is not None
    assert [sorted(cols) for cols in raw_rows] == [list(range(31))]


def test_counter_topology_blocks_can_use_local_wrapped_row0_order_in_coverage_fixture():
    scr_data = (_SCR_FIXTURE_DIR / "coverage.scr").read_bytes()

    _name, _prog_idx, data_start = _parse_header(scr_data)
    sections = _find_sections(scr_data, start=data_start)

    for rung_idx, expected_start, expected_prelude, expected_rows in (
        (
            48,
            0x4DBB,
            bytes.fromhex("0400030000012000"),
            [list(range(31)), list(range(31))],
        ),
        (
            49,
            0x5050,
            bytes.fromhex("0400030000000000012000"),
            [list(range(31))],
        ),
    ):
        sec_off, _count, _sec_end = sections[rung_idx]
        prev_sec_end = sections[rung_idx - 1][2]
        block = _find_row_topology_block(scr_data, sec_off)

        assert block is not None
        assert block.start == expected_start
        assert block.start > prev_sec_end
        assert block.prelude == expected_prelude
        assert _parse_row0_entry_order(scr_data, block) == tuple(range(1, 32)) + (0,)

        raw_rows, marker_pos = _parse_extra_row_right_wires(
            scr_data,
            block.continuation_start,
            sec_off,
            2,
        )
        assert marker_pos is not None
        assert [sorted(cols) for cols in raw_rows] == expected_rows
