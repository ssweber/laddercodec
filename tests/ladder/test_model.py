"""Tests for laddercodec.model — Contact, Coil parsing."""

import csv
from pathlib import Path

import pytest

from laddercodec import RefusedFieldWarning, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.csv.ast import EdgeCondition
from laddercodec.csv.token_parser import parse_condition_token
from laddercodec.instructions import Coil, Contact
from laddercodec.model import FieldError, Reason


def _rung_csv(path: Path, condition: str, af: str) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", condition] + ["-"] * 30 + [af])
    return path


class TestKind:
    """Contact and Coil are built by kind, operand first, and write the CSV token of it."""

    @pytest.mark.parametrize(
        ("contact", "token"),
        [
            (Contact("X001"), "X001"),
            (Contact("X001", kind="nc"), "~X001"),
            (Contact("X001", kind="nc", immediate=True), "~X001.immediate"),
            (Contact("X001", "no", True), "X001.immediate"),
            (Contact("C1", kind="rise"), "rise(C1)"),
            (Contact("C1", kind="fall", wire_down=True), "T:fall(C1)"),
        ],
    )
    def test_contact(self, contact: Contact, token: str) -> None:
        assert contact.to_csv() == token
        assert Contact.from_csv_token(token) == contact

    @pytest.mark.parametrize(
        ("coil", "token"),
        [
            (Coil("Y001"), "out(Y001)"),
            (Coil("Y001", kind="latch"), "latch(Y001)"),
            (Coil("Y001", kind="reset", range_end="Y004"), "reset(Y001..Y004)"),
            (Coil("C1", "out", "C8", oneshot=True), "out(C1..C8,oneshot=1)"),
            (Coil("Y001", kind="out", immediate=True), "out(immediate(Y001))"),
        ],
    )
    def test_coil(self, coil: Coil, token: str) -> None:
        assert coil.to_csv() == token
        assert Coil.from_csv_token(token) == coil

    @pytest.mark.parametrize("kind", ["rise", "fall"])
    def test_edge_contact_has_no_immediate_form(self, kind: str) -> None:
        with pytest.raises(FieldError) as info:
            Contact("X001", kind=kind, immediate=True)  # type: ignore[arg-type]
        assert info.value.fields == ("Contact.immediate", "Contact.kind")
        assert info.value.reason is Reason.CONFLICT

    @pytest.mark.parametrize(
        "token", ["rise(X1).immediate", "immediate(fall(X1))", "T:rise(X1).immediate"]
    )
    def test_immediate_edge_token_parses_as_an_edge(self, token: str) -> None:
        node = parse_condition_token(token)
        assert isinstance(node, EdgeCondition)
        assert node.immediate is True

    @pytest.mark.parametrize("token", ["rise(X1).immediate", "immediate(fall(X1))"])
    def test_read_csv_refuses_an_immediate_edge_on_construction(
        self, tmp_path: Path, token: str
    ) -> None:
        path = _rung_csv(tmp_path / "r.csv", token, "out(Y1)")
        with pytest.raises(FieldError, match="an edge contact has no immediate form") as info:
            read_csv(path)
        assert info.value.fields == ("Contact.immediate", "Contact.kind")
        assert info.value.location is not None

    def test_read_csv_unchecked_keeps_an_immediate_edge(self, tmp_path: Path) -> None:
        path = _rung_csv(tmp_path / "r.csv", "rise(X1).immediate", "out(Y1)")
        with pytest.warns(RefusedFieldWarning):
            [rung] = read_csv(path, unchecked=True)
        contact = rung.conditions[0][0]
        assert isinstance(contact, Contact)
        assert (contact.kind, contact.immediate) == ("rise", True)
        assert contact.to_csv() == "rise(X001).immediate"

    @pytest.mark.parametrize("value", ["2", "-1", "true"])
    def test_coil_oneshot_text_other_than_0_or_1_is_a_flag_refusal(self, value: str) -> None:
        with pytest.raises(FieldError) as info:
            Coil.from_csv_token(f"out(Y1,oneshot={value})")
        assert str(info.value) == f"Coil.oneshot: {value!r} is not 1 or 0"
        assert info.value.field == "Coil.oneshot"
        assert info.value.reason is Reason.FLAG

    def test_coil_blank_oneshot_is_missing(self) -> None:
        with pytest.raises(FieldError) as info:
            Coil.from_csv_token("out(Y1,oneshot=)")
        assert str(info.value) == "Coil.oneshot: is blank; it needs a value, 1 or 0"
        assert info.value.reason is Reason.MISSING

    @pytest.mark.parametrize(("value", "reason"), [("2", Reason.FLAG), ("", Reason.MISSING)])
    def test_read_csv_coil_oneshot_refusal(
        self, tmp_path: Path, value: str, reason: Reason
    ) -> None:
        path = _rung_csv(tmp_path / "r.csv", "X1", f"out(Y1,oneshot={value})")
        with pytest.raises(FieldError, match="Coil.oneshot") as info:
            read_csv(path)
        assert info.value.reason is reason
        # The parser raises it, so it is never kept, even read unchecked.
        with pytest.raises(FieldError, match="Coil.oneshot"):
            read_csv(path, unchecked=True)


class TestContact:
    def test_from_csv_token_no(self):
        c = Contact.from_csv_token("X001")
        assert c.kind == "no"
        assert c.operand == "X001"
        assert c.immediate is False

    def test_from_csv_token_nc(self):
        c = Contact.from_csv_token("~X003")
        assert c.kind == "nc"
        assert c.operand == "X003"
        assert c.immediate is False

    def test_from_csv_token_no_immediate(self):
        c = Contact.from_csv_token("X001.immediate")
        assert c.kind == "no"
        assert c.operand == "X001"
        assert c.immediate is True

    def test_from_csv_token_nc_immediate(self):
        c = Contact.from_csv_token("~X003.immediate")
        assert c.kind == "nc"
        assert c.operand == "X003"
        assert c.immediate is True

    def test_from_csv_token_no_immediate_wrapper(self):
        c = Contact.from_csv_token("immediate(X001)")
        assert c.kind == "no"
        assert c.operand == "X001"
        assert c.immediate is True

    def test_from_csv_token_nc_immediate_wrapper(self):
        c = Contact.from_csv_token("~immediate(X003)")
        assert c.kind == "nc"
        assert c.operand == "X003"
        assert c.immediate is True

    def test_from_csv_invalid_operand(self):
        with pytest.raises(ValueError, match="Contact.operand: 'XABC' is not a CLICK address"):
            Contact.from_csv_token("XABC")

    def test_from_csv_token_rise(self):
        c = Contact.from_csv_token("rise(X001)")
        assert c.kind == "rise"
        assert c.operand == "X001"
        assert c.immediate is False

    def test_from_csv_token_fall(self):
        c = Contact.from_csv_token("fall(X003)")
        assert c.kind == "fall"
        assert c.operand == "X003"
        assert c.immediate is False

    def test_from_csv_token_edge_immediate_rejected(self):
        with pytest.raises(
            FieldError, match="Contact.immediate: an edge contact has no immediate form"
        ):
            Contact.from_csv_token("rise(X001).immediate")

    def test_to_csv_no(self):
        c = Contact("X001")
        assert c.to_csv() == "X001"

    def test_to_csv_nc(self):
        c = Contact("X003", kind="nc")
        assert c.to_csv() == "~X003"

    def test_to_csv_edge(self):
        c = Contact("X001", kind="rise")
        assert c.to_csv() == "rise(X001)"

    def test_func_code_no(self):
        c = Contact("X001")
        assert c.func_code == "4097"

    def test_func_code_nc(self):
        c = Contact("X001", kind="nc")
        assert c.func_code == "4098"

    def test_func_code_no_immediate(self):
        c = Contact("X001", immediate=True)
        assert c.func_code == "4099"

    def test_func_code_nc_immediate(self):
        c = Contact("X001", kind="nc", immediate=True)
        assert c.func_code == "4100"

    def test_func_code_rise_fall(self):
        assert Contact("X001", kind="rise").func_code == "4101"
        assert Contact("X001", kind="fall").func_code == "4102"

    def test_to_csv_immediate(self):
        c = Contact("X001", immediate=True)
        assert c.to_csv() == "X001.immediate"


class TestCoil:
    def test_from_csv_token_out(self):
        c = Coil.from_csv_token("out(Y001)")
        assert c.kind == "out"
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_latch(self):
        c = Coil.from_csv_token("latch(Y001)")
        assert c.kind == "latch"
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_reset(self):
        c = Coil.from_csv_token("reset(Y001)")
        assert c.kind == "reset"
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_immediate_outer_rejected(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            Coil.from_csv_token("immediate(out(Y1))")

    def test_from_csv_token_immediate_inner(self):
        c = Coil.from_csv_token("out(immediate(Y1))")
        assert c.kind == "out"
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is True

    def test_from_csv_token_range(self):
        c = Coil.from_csv_token("out(Y1..Y2)")
        assert c.kind == "out"
        assert c.operand == "Y001"
        assert c.range_end == "Y002"
        assert c.immediate is False

    def test_from_csv_token_range_immediate_outer_rejected(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            Coil.from_csv_token("immediate(out(Y1..Y2))")

    def test_from_csv_token_range_immediate_inner(self):
        c = Coil.from_csv_token("out(immediate(Y1..Y2))")
        assert c.kind == "out"
        assert c.operand == "Y001"
        assert c.range_end == "Y002"
        assert c.immediate is True

    @pytest.mark.parametrize(
        ("token", "func_code"),
        [
            ("out(Y1,oneshot=1)", "8205"),
            ("out(immediate(Y1),oneshot=1)", "8206"),
            ("out(Y1..Y2,oneshot=1)", "8209"),
            ("out(immediate(Y1..Y2),oneshot=1)", "8210"),
        ],
    )
    def test_out_oneshot_func_codes(self, token, func_code):
        assert Coil.from_csv_token(token).func_code == func_code

    @pytest.mark.parametrize("token", ["latch(Y1,oneshot=1)", "reset(C1..C2,oneshot=1)"])
    def test_latch_reset_oneshot_rejected(self, token):
        # CLICK's Set/Reset dialog has no One Shot box.
        with pytest.raises(FieldError, match="Coil.oneshot: .*only out"):
            Coil.from_csv_token(token)

    def test_from_csv_token_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse coil"):
            Coil.from_csv_token("Y001")

    def test_from_csv_token_invalid_range_delimiter(self):
        with pytest.raises(ValueError, match="unsupported"):
            Coil.from_csv_token("out(Y1:Y2)")

    def test_from_csv_token_invalid_operand(self):
        with pytest.raises(ValueError, match="Coil.operand: 'YABC' is not a CLICK address"):
            Coil.from_csv_token("out(YABC)")

    def test_to_csv(self):
        c = Coil("Y001")
        assert c.to_csv() == "out(Y001)"

    def test_to_csv_immediate_canonical_inner_wrapper(self):
        c = Coil("Y1", immediate=True)
        assert c.to_csv() == "out(immediate(Y001))"

    def test_to_csv_range(self):
        c = Coil("Y1", range_end="Y2")
        assert c.to_csv() == "out(Y001..Y002)"

    def test_to_csv_range_immediate(self):
        c = Coil("Y1", range_end="Y2", immediate=True)
        assert c.to_csv() == "out(immediate(Y001..Y002))"

    def test_func_code_out(self):
        c = Coil("Y001")
        assert c.func_code == "8193"

    def test_func_code_out_immediate(self):
        c = Coil("Y1", immediate=True)
        assert c.func_code == "8197"

    def test_func_code_out_range(self):
        c = Coil("Y1", range_end="Y2")
        assert c.func_code == "8207"

    def test_func_code_out_range_immediate(self):
        c = Coil("Y1", range_end="Y2", immediate=True)
        assert c.func_code == "8208"

    def test_func_code_latch_reset(self):
        assert Coil("Y1", kind="latch").func_code == "8195"
        assert Coil("Y1", kind="reset").func_code == "8196"
