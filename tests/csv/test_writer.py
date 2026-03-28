"""Tests for laddercodec.csv.writer — decode binary → CSV round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec.csv.reader import read_golden_csv, read_multi_rung_csv
from laddercodec.csv.writer import (
    WriterError,
    decode_to_csv,
    decoded_rung_to_rows,
    write_decoded_csv,
)
from laddercodec.decode import DecodedRung, UnknownInstruction, decode_multi_rung, decode_rung
from laddercodec.encode import encode_rung
from laddercodec.encode_multi import encode_multi_rung
from laddercodec.instructions import Coil, Contact, Timer
from laddercodec.model import InstructionType

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ladder_captures" / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _golden_paths() -> list[Path]:
    """Return all golden .bin files that have a matching .csv."""
    bins = sorted(GOLDEN_DIR.glob("*.bin"))
    return [b for b in bins if b.with_suffix(".csv").exists()]


def _is_multi_rung(csv_path: Path) -> bool:
    """Check if a CSV has multiple R markers."""
    count = 0
    with open(csv_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("R,"):
                count += 1
                if count > 1:
                    return True
    return False


# ---------------------------------------------------------------------------
# Round-trip: golden.bin → decode → CSV → read_golden_csv → compare
# ---------------------------------------------------------------------------


class TestGoldenRoundTrip:
    """For each golden fixture, decode the .bin, write CSV, read it back,
    and verify the result matches the original decode output."""

    @pytest.fixture(params=[p.stem for p in _golden_paths()], ids=lambda s: s)
    def golden_stem(self, request: pytest.FixtureRequest) -> str:
        return request.param

    def test_round_trip(self, golden_stem: str, tmp_path: Path) -> None:
        bin_path = GOLDEN_DIR / f"{golden_stem}.bin"
        csv_path = GOLDEN_DIR / f"{golden_stem}.csv"
        data = bin_path.read_bytes()
        out_csv = tmp_path / f"{golden_stem}.csv"

        if _is_multi_rung(csv_path):
            rungs = decode_multi_rung(data)
            write_decoded_csv(out_csv, rungs)
            items = read_multi_rung_csv(out_csv)
            assert len(items) == len(rungs)
            for (lr, conds, afs, comment), rung in zip(items, rungs, strict=True):
                # The CSV may have fewer rows than the binary for timers
                # (padding rows stripped, auto-restored by encode).
                assert comment == rung.comment
                assert len(conds) == lr
                assert len(afs) == lr
        else:
            rung = decode_rung(data)
            write_decoded_csv(out_csv, [rung])
            lr, conds, afs, comment = read_golden_csv(out_csv)
            # The CSV may have fewer rows than the binary for non-retained
            # timers (padding stripped); read_golden_csv returns the CSV
            # row count.  The forward path auto-pads back to full height.
            assert lr <= rung.logical_rows
            assert comment == rung.comment


# ---------------------------------------------------------------------------
# Unit tests: decoded_rung_to_rows
# ---------------------------------------------------------------------------


class TestDecodedRungToRows:
    def test_simple_contact_coil(self) -> None:
        """Single row: contact → wire → coil."""
        rung = DecodedRung(
            logical_rows=1,
            condition_rows=[[Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30],
            af_tokens=[Coil(InstructionType.COIL_OUT, "Y001")],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 1
        assert rows[0][0] == "R"
        assert rows[0][1] == "X001"
        assert rows[0][2] == "-"
        assert rows[0][32] == "out(Y001)"

    def test_with_comment(self) -> None:
        """Comment produces # rows before data."""
        rung = DecodedRung(
            logical_rows=1,
            condition_rows=[[""] * 31],
            af_tokens=[""],
            comment_rtf=None,
            comment="Line 1\nLine 2",
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert rows[0][0] == "#"
        assert rows[0][1] == "Line 1"
        assert rows[1][0] == "#"
        assert rows[1][1] == "Line 2"
        assert rows[2][0] == "R"

    def test_timer_non_retained_strips_padding(self) -> None:
        """Non-retained timer: trailing blank row stripped."""
        timer = Timer("on_delay", "T1", "TD1", "1000", "Tms", retained=False)
        rung = DecodedRung(
            logical_rows=2,
            condition_rows=[
                [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
                [""] * 31,
            ],
            af_tokens=[timer, ""],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 1
        assert rows[0][32] == "on_delay(T1,TD1,preset=1000,unit=Tms)"

    def test_timer_retained_emits_reset_pin(self) -> None:
        """Retained timer: second row gets .reset() AF."""
        timer = Timer("on_delay", "T3", "TD3", "10", "Tm", retained=True)
        rung = DecodedRung(
            logical_rows=2,
            condition_rows=[
                [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
                ["-"] * 31,
            ],
            af_tokens=[timer, ""],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 2
        assert rows[0][32] == "on_delay(T3,TD3,preset=10,unit=Tm)"
        assert rows[1][0] == ""
        assert rows[1][32] == ".reset()"

    def test_nop(self) -> None:
        """NOP token serializes correctly."""
        rung = DecodedRung(
            logical_rows=1,
            condition_rows=[["-"] * 31],
            af_tokens=["NOP"],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert rows[0][32] == "NOP"

    def test_unknown_instruction_raises(self) -> None:
        """Unknown instructions cannot be written to CSV."""
        rung = DecodedRung(
            logical_rows=1,
            condition_rows=[[""] * 31],
            af_tokens=[UnknownInstruction(raw=b"\x00\x01\x02")],
            comment_rtf=None,
            comment=None,
        )
        with pytest.raises(WriterError):
            decoded_rung_to_rows(rung)


# ---------------------------------------------------------------------------
# Integration: decode_to_csv
# ---------------------------------------------------------------------------


class TestDecodeToCsv:
    def test_single_rung(self, tmp_path: Path) -> None:
        """encode → binary → decode_to_csv → read back."""
        lr = 1
        conds: list[list[str | Contact]] = [
            [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30
        ]
        afs: list[str | Coil] = [Coil(InstructionType.COIL_OUT, "Y001")]
        data = encode_rung(lr, conds, afs)  # type: ignore[arg-type]

        out = tmp_path / "out.csv"
        rungs = decode_to_csv(data, out)
        assert len(rungs) == 1
        assert out.exists()

        lr2, conds2, afs2, cmt2 = read_golden_csv(out)
        assert lr2 == lr
        assert cmt2 is None

    def test_multi_rung(self, tmp_path: Path) -> None:
        """Multi-rung encode → binary → decode_to_csv → read back."""
        rung_args = [
            (1, [["-"] * 31], ["NOP"]),
            (1, [["-"] * 31], ["NOP"]),
        ]
        data = encode_multi_rung(rung_args)  # type: ignore[arg-type]

        out = tmp_path / "out.csv"
        rungs = decode_to_csv(data, out)
        assert len(rungs) == 2
        assert out.exists()

        items = read_multi_rung_csv(out)
        assert len(items) == 2
