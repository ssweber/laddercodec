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
    _parse_row_topology_block,
    _parse_scr_tags,
    _parse_section_entries,
    _parse_wiredown_table,
    _ScrRow,
    _tag_wire_type,
    _walk_rung_records,
    decode_program,
)
from laddercodec.instructions import from_tags_af
from laddercodec.instructions.home import from_tags as home_from_tags
from laddercodec.instructions.math import Math
from laddercodec.instructions.position import from_tags as position_from_tags
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts
from laddercodec.instructions.send_receive import (
    _RD_TYPE_CODE,
    _SD_TYPE_CODE,
    Receive,
    Send,
)
from laddercodec.instructions.send_receive import from_tags as send_receive_from_tags
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
    records = _walk_rung_records(scr_data, _parse_header(scr_data))
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

    Check the counted byte framing independently of the parsed row objects.
    """
    pos = block.start + 2
    first_count = struct.unpack_from("<H", data, pos + 1)[0]
    pos += 3 + first_count * 2
    details: list[tuple[int, list[tuple[int, int]]]] = []
    for _ in range(block.row_word - 1):
        flag = data[pos]
        count = struct.unpack_from("<H", data, pos + 1)[0]
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
    assert _parse_row_block(data, 0, len(data)) == (_ScrRow(0, ((1, 0),)), 5)


def test_parse_row_block_empty_row():
    data = bytes.fromhex("010000")
    assert _parse_row_block(data, 0, len(data)) == (_ScrRow(1, ()), 3)


def test_parse_row_block_preserves_flags_and_segment_bits():
    # Row flags and per-entry segments are independent; neither identifies
    # visual row zero. The first special row can carry flags 3 and entries.
    data = bytes.fromhex("03 03 00 01 1f 01 00 00 01")
    assert _parse_row_block(data, 0, len(data)) == (
        _ScrRow(3, ((1, 31), (1, 0), (0, 1))),
        9,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "01 01 01",  # u16 count 257, not a count of 1 with ignored padding
        "01 02 00 01 00",  # truncated entries
        "01 02 00 01 00 00 00",  # duplicate column
        "01 01 00 02 00",  # unsupported entry flag
        "04 00 00",  # unsupported row flag
    ],
)
def test_parse_row_block_rejects_invalid_records(raw):
    data = bytes.fromhex(raw)
    assert _parse_row_block(data, 0, len(data)) is None


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

    assert bin_lines == csv_lines
    assert scr_lines == csv_lines


def test_decode_program_matches_shift_scr_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("shift_scr")

    assert len(scr_rungs) == len(clip_rungs) == 2
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_decode_program_matches_counter_scr_fixture():
    clip_rungs, scr_rungs = _load_fixture_pair("counter_scr")

    assert len(scr_rungs) == len(clip_rungs)
    assert [_rung_to_lines(r) for r in scr_rungs] == [_rung_to_lines(r) for r in clip_rungs]


def test_send_receive_elided_device_id_defaults():
    """SCR blobs elide fields at their class default, and the defaults differ
    per class: a Send with no 0x320E/0x60B2 tag is device_id 0, a Receive is
    device_id 1.  Verified against a native scr+clipboard pair where a Send at
    device_id 0 stored no tag while one at 1 stored both."""
    base = {
        0x220C: "2",  # protocol: modbus tcp
        0x320F: "2",  # remote_start address type: raw string
        0x6085: "DS12",  # remote_start
        0x607E: "DS3",  # source / dest
        0x622B: "10.0.0.9",
    }

    send = send_receive_from_tags("SD", _SD_TYPE_CODE, dict(base), {})
    assert isinstance(send, Send)
    assert send.target.device_id == 0

    receive = send_receive_from_tags("RD", _RD_TYPE_CODE, dict(base), {})
    assert isinstance(receive, Receive)
    assert receive.target.device_id == 1

    explicit = dict(base) | {0x320E: "5"}
    send = send_receive_from_tags("SD", _SD_TYPE_CODE, explicit, {})
    receive = send_receive_from_tags("RD", _RD_TYPE_CODE, explicit, {})
    assert send is not None and send.target.device_id == 5
    assert receive is not None and receive.target.device_id == 5


def test_time_drums_synthetic_bin_matches_canonical_csv():
    """The BIN is generated, not a native clipboard capture (be211ee)."""
    csv_rungs = read_csv(_SCR_FIXTURE_DIR / "time_drums.csv")
    clip_rungs, scr_rungs = _load_fixture_pair("time_drums")

    csv_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in csv_rungs]
    scr_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in scr_rungs]
    bin_lines = [_strip_blank_tail(_rung_to_lines(r)) for r in clip_rungs]

    assert len(scr_rungs) == 15
    assert bin_lines == csv_lines
    # Native stored wires above later rail rows must survive decoding.
    assert [i for i in range(15) if scr_lines[i] != csv_lines[i]] == [12, 13]


def test_time_drums_scr_drops_stray_pin_row_nop():
    """The drum built with a stranded reset-row NOP decodes to drum + T-wire +
    .reset() pin, with the stray NOP dropped rather than surfaced."""
    from laddercodec.instructions import Drum

    _clip, scr_rungs = _load_fixture_pair("time_drums")
    rung = scr_rungs[14]
    assert isinstance(rung.instructions[0], Drum)
    assert rung.conditions[0][1] == "T"  # column B branch wire preserved
    assert "NOP" not in rung.instructions  # stray editing-cruft NOP dropped


@pytest.mark.parametrize("flags", [*range(16), 0x80])
@pytest.mark.parametrize("comment", [None, "first"])
def test_parse_header_uses_numeric_widths_and_independent_flags(flags, comment):
    data = bytearray(_synthetic_scr([comment]))
    widths_pos = 0x43 + data[0x42] + 2
    widths = (300, *([72] * 30), 410)
    struct.pack_into("<32H", data, widths_pos, *widths)
    data[widths_pos + 64] = flags
    header = _parse_header(bytes(data))
    assert header.name == "Synth"
    assert header.prog_idx == 2
    assert header.column_widths == widths
    assert header.display_flags == flags
    assert header.rung_count == 1
    assert header.rungs_start == widths_pos + 67
    assert len(_walk_rung_records(bytes(data), header)) == 1
    program = decode_program(bytes(data))
    assert [r.comment for r in program.rungs] == ([] if comment is None else [comment])


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
    buf += struct.pack("<H", 72) * 31 + struct.pack("<H", 144)  # column widths
    buf += b"\x0d" + struct.pack("<H", len(rung_comments))  # display flags, rung count

    for index, comment in enumerate(rung_comments):
        buf += struct.pack("<H", index)  # includes rung zero
        rtf = _synthetic_rtf(comment) if comment is not None else b""
        buf += struct.pack("<I", len(rtf)) + rtf
        # Two counted rows (special + ordinary), then 32 counted down lists
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
    ordinary blocks map 1:1 to grid rows, independently of row flags."""
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
    for scr_path in sorted(_SCR_FIXTURE_DIR.glob("*.scr")):
        scr_data = scr_path.read_bytes()
        topo_map = _topology_blocks_by_section(scr_data)

        for rung_idx, block in topo_map.items():
            assert block.stored_rows[0].flags == 3
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


def test_native_time_drums_preserves_rows_above_later_rail_rows():
    program = decode_program((_SCR_FIXTURE_DIR / "time_drums.scr").read_bytes())
    for index, preceding_rows in ((12, 1), (13, 2)):
        rung = program.rungs[index]
        assert rung.logical_rows == 4
        for row in range(preceding_rows):
            assert rung.conditions[row] == ["", "T", *(["-"] * 29)]
        assert rung.conditions[preceding_rows] == ["-"] * 31
        # Wires remain positional; the drum itself is still on stored row 1.
        assert rung.instructions[0].__class__.__name__ == "Drum"
        assert "NOP" not in rung.instructions


def test_rotate_populated_special_row_is_a_real_record():
    path = _SCR_FIXTURE_DIR.parent / "tumbler/subroutines/Rotate.scr"
    data = path.read_bytes()
    header = _parse_header(data)
    records = _walk_rung_records(data, header)
    assert len(records) == header.rung_count
    block = records[24].topology
    assert block.start == 0x3858
    assert block.stored_rows[0].flags == 3
    assert block.stored_rows[0].right_cols == frozenset(range(32))
    assert block.stored_rows[0].entries[-1] == (0, 31)
    assert block.rows_right_cols == (frozenset(range(32)),)
    assert records[24].instructions == []
    assert records[25].topology.start > block.end


def test_corrupt_topology_is_not_skipped_before_a_valid_rung():
    data = bytearray(_synthetic_scr([None, "must not recover here"]))
    header = _parse_header(data)
    # Invalid row count in rung zero; later rung framing is still valid.
    struct.pack_into("<H", data, header.rungs_start + 6, 0)
    with pytest.raises(ValueError, match=r"unparseable rung topology.*rung 0"):
        decode_program(bytes(data))


@pytest.mark.parametrize("index", [0, 1])
def test_declared_rung_indices_include_zero(index):
    data = bytearray(_synthetic_scr([None, None]))
    header = _parse_header(data)
    records = _walk_rung_records(data, header)
    prefix = header.rungs_start if index == 0 else records[0].topology.end + 2
    struct.pack_into("<H", data, prefix, 42)
    with pytest.raises(ValueError, match="rung index mismatch"):
        decode_program(bytes(data))


@pytest.mark.parametrize("count", [0, 1, 3, 256])
def test_declared_rung_count_is_enforced(count):
    data = bytearray(_synthetic_scr([None, None]))
    header = _parse_header(data)
    struct.pack_into("<H", data, header.rungs_start - 2, count)
    with pytest.raises(ValueError, match="rung walk ended|truncated rung prefix"):
        decode_program(bytes(data))


def test_truncated_headers_and_rung_prefixes_raise_value_error():
    data = _synthetic_scr([None])
    header = _parse_header(data)
    for end in range(header.rungs_start + 6):
        with pytest.raises(ValueError):
            decode_program(data[:end])


def test_down_lists_use_u16_counts_and_validate_row_indices():
    # A high count byte must not be mistaken for fixed padding.
    data = struct.pack("<H", 256) + bytes([1]) * 256
    assert _parse_wiredown_table(data, 0, len(data), 1, 2) == ({0: (0,)}, len(data))
    assert _parse_wiredown_table(data[:-1], 0, len(data) - 1, 1, 2) is None
    for index in (0, 2):
        bad = struct.pack("<H", 1) + bytes([index])
        assert _parse_wiredown_table(bad, 0, len(bad), 1, 2) is None


def test_topology_column_count_is_a_count_not_an_end_marker():
    data = bytes.fromhex("02 00 03 00 00 01 01 00 01 00 01 00 00 00")
    block = _parse_row_topology_block(data, 0)
    assert block is not None
    assert block.column_count == 1
    assert block.end == len(data)
    assert block.rows_right_cols == (frozenset({0}),)
    assert _parse_row_topology_block(data[:-1], 0) is None


@pytest.mark.parametrize(
    "name",
    [
        "coverage",
        "counter_scr",
        "or_topology",
        "shift_scr",
        "time_drum_insert_rows",
        "time_drum_b_column",
    ],
)
def test_native_row_and_entry_flags_map_to_clipboard(name):
    path = _SCR_FIXTURE_DIR / f"{name}.scr"
    data = path.read_bytes()
    binary = path.with_suffix(".bin").read_bytes()
    records = _walk_rung_records(data, _parse_header(data))
    rungs = decode(binary)
    if not isinstance(rungs, list):
        rungs = [rungs]
    requests = [
        (i, row, col)
        for i, rung in enumerate(rungs)
        for row in range(rung.logical_rows)
        for col in ("A", "B", "AF")
    ]
    for cell in inspect_cells(binary, requests):
        block = records[cell.rung].topology
        stored = block.stored_rows[cell.row + 1]
        col = _COL_IDX_BY_NAME[cell.col]
        entries = {c: seg for seg, c in stored.entries}
        assert cell.raw[0x15] == (stored.flags & 1 if col == 0 else 0)
        assert cell.flags == (
            entries.get(col, 0),
            int(col in entries),
            int(cell.row in block.wiredown.get(col, ())),
        )


def test_native_drum_inserted_rows_keep_the_original_nop_wire(tmp_path):
    """Same-state native capture: the original row survives drum placement.

    Rung 1 is a normal drum; rungs 2/3 insert one/two rows above a NOP before
    placing the drum on top. The screenshot shows the horizontal wire at
    the original row's new position. There is no standalone NOP instruction
    in SCR: it is the unoccupied AF right-wire beneath the drum's span.
    """
    from laddercodec import write_csv
    from laddercodec.instructions import Drum

    base = _SCR_FIXTURE_DIR / "time_drum_insert_rows"
    data = base.with_suffix(".scr").read_bytes()
    binary = base.with_suffix(".bin").read_bytes()
    records = _walk_rung_records(data, _parse_header(data))
    clipboard, scr = _load_fixture_pair(base.name)
    assert scr == clipboard
    assert len(scr) == 3
    assert len(records) == 4  # includes CLICK's trailing empty editor rung

    for wire_row, rung in enumerate(scr):
        record = records[wire_row]
        assert len(record.instructions) == 1
        assert record.instructions[0][:3] == (0, 31, "Drum")
        assert isinstance(rung.instructions[0], Drum)
        assert rung.logical_rows == 4
        assert rung.conditions == [["-"] * 31 if row == wire_row else [""] * 31 for row in range(4)]
        assert "NOP" not in rung.instructions  # semantic tall-span suppression
        assert record.topology.wiredown == {}
        for row, stored in enumerate(record.topology.stored_rows[1:]):
            assert stored.flags == int(row == wire_row)
            assert stored.entries == (
                tuple((1, col) for col in range(32)) if row == wire_row else ()
            )

        # CellDump exposes row decoding before tall-span NOP suppression.
        drum_cell, wire_af, wire_a = inspect_cells(
            binary,
            [(wire_row, 0, "AF"), (wire_row, wire_row, "AF"), (wire_row, wire_row, "A")],
        )
        assert isinstance(drum_cell.token, Drum)
        assert drum_cell.flags == ((1, 1, 0) if wire_row == 0 else (0, 0, 0))
        assert wire_af.flags == (1, 1, 0)
        assert wire_a.raw[0x15] == 1
        if wire_row:
            assert wire_af.token == "NOP"

    expected_csv = base.with_suffix(".csv").read_text(encoding="utf-8")
    for label, rungs in (("scr", scr), ("clipboard", clipboard)):
        output = tmp_path / f"{label}.csv"
        write_csv(output, rungs, index=True)
        assert output.read_text(encoding="utf-8") == expected_csv


def test_native_drum_branch_above_original_nop_row_is_preserved(tmp_path):
    """A later all-segment-1 rail row does not make preceding wires debris."""
    from laddercodec import write_csv
    from laddercodec.instructions import Drum

    base = _SCR_FIXTURE_DIR / "time_drum_b_column"
    data = base.with_suffix(".scr").read_bytes()
    binary = base.with_suffix(".bin").read_bytes()
    clipboard, scr = _load_fixture_pair(base.name)
    assert scr == clipboard
    assert len(scr) == 1
    rung = scr[0]
    assert rung.logical_rows == 4
    assert rung.conditions == [
        ["", "T", *(["-"] * 29)],
        ["-"] * 31,
        [""] * 31,
        [""] * 31,
    ]
    assert isinstance(rung.instructions[0], Drum)
    assert rung.instructions[1:] == ["", "", ""]

    block = _walk_rung_records(data, _parse_header(data))[0].topology
    upper, original = block.stored_rows[1:3]
    # These are the precise features the removed row-deletion rule used:
    # a nonempty row before a rail-connected row with every segment bit set.
    assert upper.flags == 0
    assert upper.entries == ((0, 1), *tuple((1, col) for col in range(2, 31)))
    assert original.flags == 1
    assert original.entries == tuple((1, col) for col in range(32))
    assert block.wiredown == {1: (0,)}

    upper_b, original_af = inspect_cells(binary, [(0, 0, "B"), (0, 1, "AF")])
    assert upper_b.flags == (0, 1, 1)
    assert original_af.flags == (1, 1, 0)
    assert original_af.token == "NOP"  # covered by the drum in semantic output

    for label, rungs in (("scr", scr), ("clipboard", clipboard)):
        output = tmp_path / f"{label}.csv"
        write_csv(output, rungs, index=True)
        assert output.read_text(encoding="utf-8") == base.with_suffix(".csv").read_text(
            encoding="utf-8"
        )
