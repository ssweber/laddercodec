"""Tests for laddercodec.model — Contact, Coil parsing."""

import pytest

from laddercodec.instructions import Coil, Contact
from laddercodec.model import InstructionType


class TestContact:
    def test_from_csv_token_no(self):
        c = Contact.from_csv_token("X001")
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"
        assert c.immediate is False

    def test_from_csv_token_nc(self):
        c = Contact.from_csv_token("~X003")
        assert c.type == InstructionType.CONTACT_NC
        assert c.operand == "X003"
        assert c.immediate is False

    def test_from_csv_token_no_immediate(self):
        c = Contact.from_csv_token("X001.immediate")
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"
        assert c.immediate is True

    def test_from_csv_token_nc_immediate(self):
        c = Contact.from_csv_token("~X003.immediate")
        assert c.type == InstructionType.CONTACT_NC
        assert c.operand == "X003"
        assert c.immediate is True

    def test_from_csv_token_no_immediate_wrapper(self):
        c = Contact.from_csv_token("immediate(X001)")
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"
        assert c.immediate is True

    def test_from_csv_token_nc_immediate_wrapper(self):
        c = Contact.from_csv_token("~immediate(X003)")
        assert c.type == InstructionType.CONTACT_NC
        assert c.operand == "X003"
        assert c.immediate is True

    def test_from_csv_invalid_operand(self):
        with pytest.raises(ValueError, match="Invalid operand"):
            Contact.from_csv_token("XABC")

    def test_from_csv_token_rise(self):
        c = Contact.from_csv_token("rise(X001)")
        assert c.type == InstructionType.CONTACT_EDGE
        assert c.edge_kind == "rise"
        assert c.operand == "X001"
        assert c.immediate is False

    def test_from_csv_token_fall(self):
        c = Contact.from_csv_token("fall(X003)")
        assert c.type == InstructionType.CONTACT_EDGE
        assert c.edge_kind == "fall"
        assert c.operand == "X003"
        assert c.immediate is False

    def test_from_csv_token_edge_immediate_rejected(self):
        with pytest.raises(ValueError, match="Immediate edge contacts are unsupported"):
            Contact.from_csv_token("rise(X001).immediate")

    def test_to_csv_no(self):
        c = Contact(InstructionType.CONTACT_NO, "X001")
        assert c.to_csv() == "X001"

    def test_to_csv_nc(self):
        c = Contact(InstructionType.CONTACT_NC, "X003")
        assert c.to_csv() == "~X003"

    def test_to_csv_edge(self):
        c = Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="rise")
        assert c.to_csv() == "rise(X001)"

    def test_func_code_no(self):
        c = Contact(InstructionType.CONTACT_NO, "X001")
        assert c.func_code == "4097"

    def test_func_code_nc(self):
        c = Contact(InstructionType.CONTACT_NC, "X001")
        assert c.func_code == "4098"

    def test_func_code_no_immediate(self):
        c = Contact(InstructionType.CONTACT_NO, "X001", immediate=True)
        assert c.func_code == "4099"

    def test_func_code_nc_immediate(self):
        c = Contact(InstructionType.CONTACT_NC, "X001", immediate=True)
        assert c.func_code == "4100"

    def test_func_code_rise_fall(self):
        assert Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="rise").func_code == "4101"
        assert Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="fall").func_code == "4102"

    def test_to_csv_immediate(self):
        c = Contact(InstructionType.CONTACT_NO, "X001", immediate=True)
        assert c.to_csv() == "X001.immediate"


class TestCoil:
    def test_from_csv_token_out(self):
        c = Coil.from_csv_token("out(Y001)")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_latch(self):
        c = Coil.from_csv_token("latch(Y001)")
        assert c.type == InstructionType.COIL_LATCH
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_reset(self):
        c = Coil.from_csv_token("reset(Y001)")
        assert c.type == InstructionType.COIL_RESET
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_immediate_outer_rejected(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            Coil.from_csv_token("immediate(out(Y1))")

    def test_from_csv_token_immediate_inner(self):
        c = Coil.from_csv_token("out(immediate(Y1))")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y1"
        assert c.range_end is None
        assert c.immediate is True

    def test_from_csv_token_range(self):
        c = Coil.from_csv_token("out(Y1..Y2)")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y1"
        assert c.range_end == "Y2"
        assert c.immediate is False

    def test_from_csv_token_range_immediate_outer_rejected(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            Coil.from_csv_token("immediate(out(Y1..Y2))")

    def test_from_csv_token_range_immediate_inner(self):
        c = Coil.from_csv_token("out(immediate(Y1..Y2))")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y1"
        assert c.range_end == "Y2"
        assert c.immediate is True

    def test_from_csv_token_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse coil"):
            Coil.from_csv_token("Y001")

    def test_from_csv_token_invalid_range_delimiter(self):
        with pytest.raises(ValueError, match="unsupported"):
            Coil.from_csv_token("out(Y1:Y2)")

    def test_from_csv_token_invalid_operand(self):
        with pytest.raises(ValueError, match="Invalid operand"):
            Coil.from_csv_token("out(YABC)")

    def test_to_csv(self):
        c = Coil(InstructionType.COIL_OUT, "Y001")
        assert c.to_csv() == "out(Y001)"

    def test_to_csv_immediate_canonical_inner_wrapper(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", immediate=True)
        assert c.to_csv() == "out(immediate(Y1))"

    def test_to_csv_range(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2")
        assert c.to_csv() == "out(Y1..Y2)"

    def test_to_csv_range_immediate(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2", immediate=True)
        assert c.to_csv() == "out(immediate(Y1..Y2))"

    def test_func_code_out(self):
        c = Coil(InstructionType.COIL_OUT, "Y001")
        assert c.func_code == "8193"

    def test_func_code_out_immediate(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", immediate=True)
        assert c.func_code == "8197"

    def test_func_code_out_range(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2")
        assert c.func_code == "8207"

    def test_func_code_out_range_immediate(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2", immediate=True)
        assert c.func_code == "8208"

    def test_func_code_latch_reset(self):
        assert Coil(InstructionType.COIL_LATCH, "Y1").func_code == "8195"
        assert Coil(InstructionType.COIL_RESET, "Y1").func_code == "8196"
