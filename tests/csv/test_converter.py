"""Tests for laddercodec.csv.converter."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec.csv.ast import (
    AfBlank,
    AfCall,
    BlankCondition,
    ComparisonCondition,
    ContactCondition,
    EdgeCondition,
    HorizontalWire,
)
from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER
from laddercodec.csv.converter import (
    ConvertError,
    af_node_to_token,
    condition_node_to_token,
    convert_rung,
    strip_tall_padding,
)
from laddercodec.csv.parser import parse_csv_file
from laddercodec.instructions import Coil, CompareContact, Contact, RawInstruction, Timer
from laddercodec.model import InstructionType


def _write_csv(path: Path, rows: list[tuple[str, list[str], str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for marker, conditions, af in rows:
            writer.writerow([marker, *conditions, af])


def _blank() -> list[str]:
    return [""] * len(CONDITION_COLUMNS)


def _wire_row(contact: str = "X001", col: int = 0) -> list[str]:
    row = ["-"] * len(CONDITION_COLUMNS)
    row[col] = contact
    return row


class TestConvertSimpleRungs:
    def test_coil_rung(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        _write_csv(csv_path, [("R", _wire_row(), "out(Y001)")])

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, comment = convert_rung(rung)
        assert lr == 1
        assert isinstance(conds[0][0], Contact)
        assert isinstance(afs[0], Coil)
        assert comment is None

    def test_nop_rung(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        _write_csv(csv_path, [("R", _wire_row(), "NOP")])

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 1
        assert afs[0] == "NOP"

    def test_comment_extracted(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        cmt = ["comment text"] + [""] * (len(CONDITION_COLUMNS) - 1)
        _write_csv(
            csv_path,
            [
                ("#", cmt, ""),
                ("R", _wire_row(), "out(Y001)"),
            ],
        )
        rung = parse_csv_file(csv_path).rungs[0]
        _, _, _, comment = convert_rung(rung)
        assert comment == "comment text"


class TestTimerAutopad:
    def test_non_retentive_auto_adds_blank_row(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        _write_csv(csv_path, [("R", _wire_row(), "on_delay(T1,TD1,preset=1000,unit=Tms)")])

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 2
        assert isinstance(afs[0], Timer)
        assert afs[0].retained is False
        assert afs[1] == ""
        assert all(c == "" for c in conds[1])  # blank padding row

    def test_off_delay_auto_adds_blank_row(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        _write_csv(csv_path, [("R", _wire_row(), "off_delay(T2,TD2,preset=500,unit=Ts)")])

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 2
        assert isinstance(afs[0], Timer)
        assert afs[1] == ""

    def test_no_autopad_when_user_provides_two_rows(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        wires = ["-"] * len(CONDITION_COLUMNS)
        _write_csv(
            csv_path,
            [
                ("R", _wire_row(), "on_delay(T1,TD1,preset=1000,unit=Tms)"),
                ("", wires, ""),
            ],
        )

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 2
        assert all(c == "-" for c in conds[1])  # user wires preserved


class TestPinRows:
    def test_reset_makes_timer_retentive(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        wires = ["-"] * len(CONDITION_COLUMNS)
        _write_csv(
            csv_path,
            [
                ("R", _wire_row(), "on_delay(T1,TD1,preset=1000,unit=Tms)"),
                ("", wires, ".reset()"),
            ],
        )

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 2
        timer = afs[0]
        assert isinstance(timer, Timer)
        assert timer.retained is True
        assert afs[1] == ""  # .reset() absorbed, not emitted

    def test_reset_with_condition(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        reset_row = _wire_row("X002")
        _write_csv(
            csv_path,
            [
                ("R", _wire_row("X001"), "on_delay(T1,TD1,preset=1000,unit=Tms)"),
                ("", reset_row, ".reset()"),
            ],
        )

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 2
        assert isinstance(afs[0], Timer) and afs[0].retained is True
        assert isinstance(conds[1][0], Contact)
        assert conds[1][0].operand == "X002"
        assert afs[1] == ""

    def test_reset_without_timer_parent_is_noop(self, tmp_path: Path) -> None:
        """If .reset() appears but parent AF isn't a timer, it's just absorbed."""
        csv_path = tmp_path / "main.csv"
        wires = ["-"] * len(CONDITION_COLUMNS)
        _write_csv(
            csv_path,
            [
                ("R", _wire_row(), "out(Y001)"),
                ("", wires, ".reset()"),
            ],
        )

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung)
        assert lr == 2
        assert isinstance(afs[0], Coil)
        assert afs[1] == ""

    def test_unknown_pin_raises(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        wires = ["-"] * len(CONDITION_COLUMNS)
        _write_csv(
            csv_path,
            [
                ("R", _wire_row(), "on_delay(T1,TD1,preset=1000,unit=Tms)"),
                ("", wires, ".bogus()"),
            ],
        )

        rung = parse_csv_file(csv_path).rungs[0]
        with pytest.raises(ConvertError, match="Unknown pin"):
            convert_rung(rung)


class TestStripTallPadding:
    def test_strips_blank_trailing_row(self) -> None:
        timer = Timer("on_delay", "T1", "TD1", "1000", "Tms")
        conds = [
            [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
            [""] * 31,
        ]
        afs: list[object] = [timer, ""]
        lr, new_conds, new_afs = strip_tall_padding(2, conds, afs)
        assert lr == 1
        assert len(new_conds) == 1
        assert len(new_afs) == 1

    def test_keeps_row_with_wires(self) -> None:
        timer = Timer("on_delay", "T1", "TD1", "1000", "Tms")
        conds = [
            [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
            ["-"] * 31,
        ]
        afs: list[object] = [timer, ""]
        lr, new_conds, new_afs = strip_tall_padding(2, conds, afs)
        assert lr == 2  # kept because row has wires

    def test_keeps_row_with_contacts(self) -> None:
        timer = Timer("on_delay", "T1", "TD1", "1000", "Tms", retained=True)
        conds = [
            [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
            [Contact(InstructionType.CONTACT_NO, "X002")] + ["-"] * 30,
        ]
        afs: list[object] = [timer, ""]
        lr, new_conds, new_afs = strip_tall_padding(2, conds, afs)
        assert lr == 2

    def test_no_strip_for_non_timer(self) -> None:
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        conds = [
            [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
            [""] * 31,
        ]
        afs: list[object] = [coil, ""]
        lr, new_conds, new_afs = strip_tall_padding(2, conds, afs)
        assert lr == 2  # not a tall instruction, no strip

    def test_single_row_passthrough(self) -> None:
        timer = Timer("on_delay", "T1", "TD1", "1000", "Tms")
        conds = [[Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30]
        afs: list[object] = [timer]
        lr, new_conds, new_afs = strip_tall_padding(1, conds, afs)
        assert lr == 1


class TestConditionNodeToToken:
    def test_blank(self) -> None:
        assert condition_node_to_token(BlankCondition()) == ""

    def test_wire(self) -> None:
        assert condition_node_to_token(HorizontalWire()) == "-"

    def test_contact_no(self) -> None:
        node = ContactCondition(operand="X001", negated=False, immediate=False)
        result = condition_node_to_token(node)
        assert isinstance(result, Contact)
        assert result.type == InstructionType.CONTACT_NO
        assert result.operand == "X001"

    def test_contact_wire_down(self) -> None:
        node = ContactCondition(operand="X001", negated=False, immediate=False, wire_down=True)
        result = condition_node_to_token(node)
        assert isinstance(result, Contact)
        assert result.wire_down is True

    def test_edge_wire_down(self) -> None:
        node = EdgeCondition(kind="rise", operand="X002", wire_down=True)
        result = condition_node_to_token(node)
        assert isinstance(result, Contact)
        assert result.type == InstructionType.CONTACT_EDGE
        assert result.wire_down is True

    def test_compare_wire_down(self) -> None:
        node = ComparisonCondition(left="DS1", op="==", right="1", wire_down=True)
        result = condition_node_to_token(node)
        assert isinstance(result, CompareContact)
        assert result.wire_down is True

    def test_immediate(self) -> None:
        node = ContactCondition(operand="X001", negated=False, immediate=True)
        result = condition_node_to_token(node)
        assert isinstance(result, Contact)
        assert result.immediate is True


class TestAfNodeToToken:
    def test_blank(self) -> None:
        assert af_node_to_token(AfBlank()) == ""

    def test_nop(self) -> None:
        assert af_node_to_token(AfCall(name="NOP", args=(), known=False)) == "NOP"

    def test_coil(self) -> None:
        node = AfCall(name="out", args=("Y001",), known=True)
        result = af_node_to_token(node)
        assert isinstance(result, Coil)
        assert result.type == InstructionType.COIL_OUT
        assert result.operand == "Y001"

    def test_coil_immediate_range(self) -> None:
        node = AfCall(name="out", args=("immediate(Y1..Y2)",), known=True)
        result = af_node_to_token(node)
        assert isinstance(result, Coil)
        assert result.immediate is True
        assert result.operand == "Y1"
        assert result.range_end == "Y2"

    def test_timer(self) -> None:
        node = AfCall(
            name="on_delay",
            args=("T1", "TD1"),
            known=True,
            kwargs={"preset": "1000", "unit": "Tms"},
        )
        result = af_node_to_token(node)
        assert isinstance(result, Timer)
        assert result.timer_type == "on_delay"
        assert result.done_bit == "T1"
        assert result.setpoint == "1000"

    def test_raw(self) -> None:
        # Minimal valid blob: class name "X" + type marker + part count + field count(0)
        blob_hex = "580000002711000001000000000000"
        node = AfCall(name="raw", args=("X", blob_hex), known=False)
        result = af_node_to_token(node)
        assert isinstance(result, RawInstruction)
        assert result.class_name == "X"
        assert result.blob == bytes.fromhex(blob_hex)

    def test_unsupported_raises_by_default(self) -> None:
        node = AfCall(name="count_up", args=("C1", "DS1"), known=True)
        with pytest.raises(ValueError, match="Unsupported AF instruction"):
            af_node_to_token(node)

    def test_unsupported_returns_blank_when_not_strict(self) -> None:
        node = AfCall(name="count_up", args=("C1", "DS1"), known=True)
        assert af_node_to_token(node, strict=False) == ""


class TestConvertRungStrict:
    def test_unsupported_af_raises_by_default(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        _write_csv(csv_path, [("R", _wire_row(), "count_up(C1,DS1)")])

        rung = parse_csv_file(csv_path).rungs[0]
        with pytest.raises(ValueError, match="Unsupported AF instruction"):
            convert_rung(rung)

    def test_unsupported_af_blanked_when_not_strict(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        _write_csv(csv_path, [("R", _wire_row(), "count_up(C1,DS1)")])

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, comment = convert_rung(rung, strict=False)
        assert lr == 1
        assert afs[0] == ""
        assert isinstance(conds[0][0], Contact)
        assert conds[0][0].operand == "X001"

    def test_unsupported_af_with_pin_row_not_strict(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "main.csv"
        wires = ["-"] * len(CONDITION_COLUMNS)
        _write_csv(
            csv_path,
            [
                ("R", _wire_row(), "count_up(C1,DS1)"),
                ("", wires, ".reset()"),
            ],
        )

        rung = parse_csv_file(csv_path).rungs[0]
        lr, conds, afs, _ = convert_rung(rung, strict=False)
        assert lr == 2
        assert afs[0] == ""
        assert afs[1] == ""
