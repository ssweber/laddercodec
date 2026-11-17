"""Tests that a Copy of a TXT source accepts the options that CLICK's dialog offers for it.

When you copy a TXT register into a number register, CLICK's dialog asks you to pick Copy
Character Value (``to_value``) or Copy ASCII Code Value (``to_ascii``). CLICK saves a TXT
register copied into DF as a plain copy. When you copy a TXT register or range into TXT, the
only option the dialog offers is Termination Code. The dialog greys Suppress zero for a TXT
source. The CLICK v4 captures that these tests read are in
``tests/fixtures/v4_captures/copy_txt/``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import decode, decode_program
from laddercodec.binary_helpers import _build_blob
from laddercodec.csv import CSV_HEADER, read_csv
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.copy import BlockCopy, Copy, from_tags
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts
from laddercodec.instructions.send_receive import ModbusRtuTarget, Receive
from laddercodec.operands.errors import FieldError, Reason
from laddercodec.operands.unchecked import refusals, stored_blob

CAPTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_txt"


def _tags(blob: bytes) -> dict[int, str]:
    """Return the value of every tag in *blob*, keyed by tag."""
    return {tag: value for tag, _sentinel, value in _decompose_blob(blob)[4]}


def _clip_blob(clip: bytes) -> bytes:
    """Return the Copy blob from a clipboard capture that holds one Copy.

    The blob runs from the class name ``Copy`` to the end of the buffer.
    """
    return clip[clip.index("Copy".encode("utf-16-le") + b"\x00\x00") :]


def _one(rungs: object) -> Copy | BlockCopy:
    rung = rungs[0]
    [found] = [t for t in rung.instructions if isinstance(t, (Copy, BlockCopy))]
    return found


def _errors(build) -> list[FieldError]:
    with pytest.raises(FieldError) as raised:
        build()
    return list(raised.value.errors)


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    path.write_text(
        ",".join(CSV_HEADER) + "\n" + ",".join(["R", "X001"] + ["-"] * 30 + [f'"{af}"']) + "\n",
        encoding="utf-8",
    )
    [found] = [t for t in read_csv(path)[0].instructions if t]
    return found


# ---------------------------------------------------------------------------
# CLICK's captures
# ---------------------------------------------------------------------------

#: The file name of each capture and the CSV token that its decoded Copy writes.
CAPTURED = [
    ("case01", "copy(TXT1,YD0,convert=to_value)"),
    ("case02", "copy(TXT1,YD0,convert=to_ascii)"),
    ("case03", "copy(TXT1,TXT21)"),
    ("case04", "copy(TXT1,TXT21,termination_code=$00)"),
    ("case05", "copy(TXT1,TXT21,termination_code=$0D)"),
    ("case06", "blockcopy(TXT1..TXT2,TXT11..TXT12)"),
    ("case07", "blockcopy(TXT1..TXT2,TXT11..TXT12,termination_code=$00)"),
    ("case08", "blockcopy(TXT1..TXT2,TXT11..TXT12,termination_code=$0D)"),
]

#: The captures that have no termination code. CLICK v4 sets the text flag 0x1201 on every
#: save and ignores it on load. laddercodec sets the flag only for a termination code or a
#: text constant, so in these captures the flag differs.
_NO_CODE = ("case01", "case02", "case03", "case06")


@pytest.mark.parametrize(("case", "csv"), CAPTURED)
def test_a_click_capture_decodes_with_its_options(case: str, csv: str) -> None:
    clip = (CAPTURES / f"{case}.bin").read_bytes()
    from_clip = _one(decode(clip))
    from_scr = _one(decode_program((CAPTURES / f"{case}.scr").read_bytes()).rungs)
    for found in (from_clip, from_scr):
        assert found.to_csv() == csv
        assert not refusals(found)
        assert stored_blob(found) is None
    assert from_clip == from_scr


@pytest.mark.parametrize(("case", "csv"), CAPTURED)
def test_the_copy_a_capture_reads_as_writes_clicks_tags(
    tmp_path: Path, case: str, csv: str
) -> None:
    """A Copy read from a capture's CSV token writes the same tags as CLICK's clipboard. The
    one exception is the text flag in the captures where CLICK sets it and laddercodec does
    not."""
    click = _tags(_clip_blob((CAPTURES / f"{case}.bin").read_bytes()))
    built = _read_af(tmp_path, csv)
    assert isinstance(built, (Copy, BlockCopy))
    assert built.to_csv() == csv
    ours = _tags(built.build_blob())
    if case in _NO_CODE:
        assert (click.pop(0x1201), ours.pop(0x1201)) == ("-1", "0")
    assert ours == click
    assert parse_af_blob(built.build_blob()) == built
    if csv.startswith("copy"):
        assert Copy.from_csv_token(csv) == built


@pytest.mark.parametrize("mode", ["single", "block"])
@pytest.mark.parametrize(
    ("termination", "expected"),
    [
        ({0x1221: ""}, "$00"),  # CLICK's program file leaves 0x3216 out for $00
        ({0x1221: "", 0x3216: "0"}, "$00"),
        ({0x1221: "", 0x3216: "13"}, "$0D"),
        ({0x3216: "13"}, "0"),  # without flag 0x1221 there is no code
        ({}, "0"),
    ],
)
def test_the_termination_tags_read_as_the_code(
    mode: str, termination: dict[int, str], expected: str
) -> None:
    tags = {0x6074: "TXT1", 0x6076: "TXT21", **termination}
    if mode == "block":
        tags |= {0x6075: "TXT2", 0x6076: "TXT11", 0x6077: "TXT12", 0x2223: "1"}
    found = from_tags("Copy", 0x2721, tags)
    assert isinstance(found, BlockCopy if mode == "block" else Copy)
    assert found.termination_code == expected
    assert not refusals(found)


@pytest.mark.parametrize("mode", ["single", "block"])
def test_a_termination_code_that_is_no_number_stays_raw(mode: str) -> None:
    tags = {0x6074: "TXT1", 0x6076: "TXT21", 0x1221: "", 0x3216: "x"}
    if mode == "block":
        tags |= {0x6075: "TXT2", 0x6076: "TXT11", 0x6077: "TXT12", 0x2223: "1"}
    assert from_tags("Copy", 0x2721, tags) is None


# ---------------------------------------------------------------------------
# A TXT register into a number register
# ---------------------------------------------------------------------------

#: Number registers a single Copy of a TXT register writes by value or ASCII code.
TXT_CHOICE_DESTS = ["DS1", "DD1", "DH1", "YD0", "TD1", "CTD1", "DS[DS1]", "YD[DS1]", "CTD[DS1]"]


@pytest.mark.parametrize("destination", TXT_CHOICE_DESTS)
@pytest.mark.parametrize("source", ["TXT1", "TXT[DS1]"])
def test_a_txt_register_into_a_number_needs_value_or_ascii(source: str, destination: str) -> None:
    """A plain copy of a TXT register into a number register other than DF is refused.
    CLICK's dialog makes you pick Copy Character Value or Copy ASCII Code Value, so CLICK
    never saves a plain copy of this kind. Each of the two options writes its tags and decodes back to the same Copy."""
    [error] = _errors(lambda: Copy(source, destination))
    assert error.fields == ("Copy.convert", "Copy.source", "Copy.dest")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)
    assert "convert=to_value" in str(error) and "convert=to_ascii" in str(error)
    for fmt, conv, field4 in (("to_value", "5", "0"), ("to_ascii", "6", "1")):
        copy = Copy(source, destination, convert=fmt)
        written = _tags(copy.build_blob())
        assert (written[0x2227], written[0x2206]) == (conv, field4)
        assert parse_af_blob(copy.build_blob()) == copy


def test_a_bare_txt_copy_into_a_number_is_refused_from_csv(tmp_path: Path) -> None:
    with pytest.raises(FieldError, match="Copy.convert: 'TXT1' -> 'YD0' needs convert=to_value"):
        _read_af(tmp_path, "copy(TXT1,YD0)")
    with pytest.raises(FieldError, match="needs convert=to_value"):
        Copy.from_csv_token("copy(TXT1,YD0)")


@pytest.mark.parametrize(("source", "destination"), [("TXT1", "DF1"), ("TXT1", "DF[DS1]")])
def test_a_txt_register_into_df_is_a_plain_copy(source: str, destination: str) -> None:
    """CLICK saves a TXT register copied into DF as a plain copy."""
    copy = Copy(source, destination)
    assert _tags(copy.build_blob())[0x2227] == "0"
    assert copy.to_csv() == f"copy({source},{destination})"


def test_a_stored_plain_txt_copy_into_a_number_keeps_its_refusal() -> None:
    """laddercodec 0.4.0 wrote a plain copy of TXT1 into DS1. Such a blob decodes as a Copy
    that keeps the refusal. While its fields are unchanged, the Copy writes the bytes that it
    was decoded from."""
    tags = {0x6074: "TXT1", 0x6076: "DS1"}
    blob = _build_blob("Copy", 0x2721, tuple(tags) + (0x0000,), [*tags.values(), ""])
    parsed = parse_af_blob(blob)
    assert isinstance(parsed, Copy)
    assert parsed.convert is None
    [error] = refusals(parsed)
    assert error.fields == ("Copy.convert", "Copy.source", "Copy.dest")
    assert parsed.build_blob() == blob
    with pytest.raises(FieldError, match="needs convert=to_value"):
        replace(parsed)


# ---------------------------------------------------------------------------
# Suppress zero
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "destination", "fmt"),
    [
        ("TXT1", "YD0", "to_value"),
        ("TXT1", "DS1", "to_ascii"),
        ("TXT1", "TXT21", None),
        ("TXT[DS1]", "DS1", "to_value"),
        ("TXT1", "DF1", None),
    ],
)
def test_suppress_zero_on_a_txt_source_is_refused(source: str, destination: str, fmt: str) -> None:
    """CLICK's dialog greys Suppress zero for a TXT source, into a number or into TXT."""
    [error] = _errors(lambda: Copy(source, destination, convert=fmt, suppress_zero=True))
    assert error.fields == ("Copy.suppress_zero", "Copy.source")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)
    # Suppress zero turned off is accepted. Every Copy that does not convert to text has it
    # off.
    Copy(source, destination, convert=fmt, suppress_zero=False)


# ---------------------------------------------------------------------------
# Termination code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "term_char"), [("$00", "0"), ("$0D", "13"), ("$0d", "13"), ("$FF", "255")]
)
@pytest.mark.parametrize(("source", "destination"), [("TXT1", "TXT21"), ("TXT[DS1]", "TXT[DS2]")])
def test_a_txt_register_into_txt_takes_a_termination_code(
    source: str, destination: str, code: str, term_char: str
) -> None:
    copy = Copy(source, destination, termination_code=code)
    assert copy.termination_code == code.upper()
    written = _tags(copy.build_blob())
    assert (written[0x1221], written[0x3216], written[0x1201]) == ("-1", term_char, "-1")
    assert (written[0x2227], written[0x2206]) == ("0", "0")
    assert copy.to_csv() == f"copy({source},{destination},termination_code={copy.termination_code})"
    assert parse_af_blob(copy.build_blob()) == copy
    assert Copy.from_csv_token(copy.to_csv()) == copy


@pytest.mark.parametrize("code", ["none", "0"])
def test_no_termination_code_writes_none(code: str) -> None:
    copy = Copy.from_csv_token(f"copy(TXT1,TXT21,termination_code={code})")
    assert copy.termination_code == "0"
    assert copy.to_csv() == "copy(TXT1,TXT21)"
    assert _tags(copy.build_blob())[0x1221] == "0"


@pytest.mark.parametrize(
    ("source", "destination", "fmt"),
    [
        ('"AB"', "TXT1", None),  # a constant into TXT, where the dialog greys the box
        ("$41", "TXT1", None),
        ("TXT1", "YD0", "to_value"),  # a TXT register into a number
        ("TXT1", "DS1", "to_ascii"),
        ("TXT1", "DF1", None),
        ("DS1", "DS2", None),
    ],
)
def test_a_termination_code_is_refused_where_the_dialog_greys_it(
    source: str, destination: str, fmt: str | None
) -> None:
    errors = _errors(lambda: Copy(source, destination, convert=fmt, termination_code="$0D"))
    [error] = [e for e in errors if e.field == "Copy.termination_code"]
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)


def test_a_termination_code_beside_a_converter_goes_inside_it() -> None:
    with pytest.raises(FieldError, match="inside the converter") as raised:
        Copy.from_csv_token("copy(DS1,TXT1,convert=to_text(suppress_zero=1),termination_code=$0D)")
    assert raised.value.fields == ("Copy.termination_code", "Copy.convert")
    assert raised.value.reason is Reason.CONFLICT


@pytest.mark.parametrize("code", ["$D", "$ZZ", "13", ""])
def test_a_txt_copy_refuses_a_code_that_is_no_character_code(code: str) -> None:
    errors = _errors(lambda: Copy("TXT1", "TXT21", termination_code=code))
    assert errors[0].field == "Copy.termination_code"


# ---------------------------------------------------------------------------
# Block Copy of TXT into TXT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("code", "term_char"), [("$00", "0"), ("$0D", "13")])
def test_a_block_of_txt_into_txt_takes_a_termination_code(code: str, term_char: str) -> None:
    block = BlockCopy("TXT1", "TXT2", "TXT11", "TXT12", termination_code=code)
    written = _tags(block.build_blob())
    assert (written[0x1221], written[0x3216], written[0x1201]) == ("-1", term_char, "-1")
    assert (written[0x2227], written[0x2223]) == ("0", "1")
    assert block.to_csv() == f"blockcopy(TXT1..TXT2,TXT11..TXT12,termination_code={code})"
    parsed = parse_af_blob(block.build_blob())
    assert parsed == block
    # The program file's tags build the same Block Copy.
    class_name, type_code, _parts, _extra, fields = _decompose_blob(block.build_blob())
    assert from_tags_af(class_name, type_code, *_fields_to_tag_dicts(fields)) == block


def test_a_block_with_no_code_writes_as_before() -> None:
    block = BlockCopy("TXT1", "TXT2", "TXT11", "TXT12", termination_code="none")
    assert block.termination_code == "0"
    written = _tags(block.build_blob())
    assert (written[0x1221], written[0x3216], written[0x1201]) == ("0", "0", "0")
    assert block.to_csv() == "blockcopy(TXT1..TXT2,TXT11..TXT12)"


@pytest.mark.parametrize("fmt", ["to_value", "to_ascii"])
def test_a_block_of_txt_into_txt_refuses_a_converter(fmt: str) -> None:
    """A Block Copy of a TXT range into TXT refuses a converter. For this copy, the only
    option that CLICK's dialog offers is Termination Code."""
    [error] = _errors(lambda: BlockCopy("TXT1", "TXT2", "TXT11", "TXT12", convert=fmt))
    assert error.fields == ("BlockCopy.convert", "BlockCopy.dest_start")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)


@pytest.mark.parametrize(
    ("source", "dest", "fmt"),
    [
        (("TXT1", "TXT2"), ("DS1", "DS2"), "to_value"),  # a TXT range into a number
        (("DS1", "DS2"), ("DS11", "DS12"), None),
        (("TXT1", "TXT2"), ("TXT11", "TXT12"), "to_ascii"),
    ],
)
def test_a_block_termination_code_is_refused_but_for_txt_into_txt(source, dest, fmt) -> None:
    errors = _errors(lambda: BlockCopy(*source, *dest, convert=fmt, termination_code="$0D"))
    [error] = [e for e in errors if e.field == "BlockCopy.termination_code"]
    assert error.fields == (
        "BlockCopy.termination_code",
        "BlockCopy.source_start",
        "BlockCopy.dest_start",
    )
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)


@pytest.mark.parametrize(
    ("code", "reason"), [("$D", Reason.FORM), ("13", Reason.FORM), ("", Reason.MISSING)]
)
def test_a_block_refuses_a_code_that_is_no_character_code(code: str, reason: Reason) -> None:
    errors = _errors(lambda: BlockCopy("TXT1", "TXT2", "TXT11", "TXT12", termination_code=code))
    assert errors[0].field == "BlockCopy.termination_code"
    assert errors[0].reason is reason


def test_a_block_termination_code_reads_from_csv(tmp_path: Path) -> None:
    token = "blockcopy(TXT1..TXT2,TXT11..TXT12,oneshot=1,termination_code=$0d)"
    block = _read_af(tmp_path, token)
    assert block == BlockCopy(
        "TXT1", "TXT2", "TXT11", "TXT12", oneshot=True, termination_code="$0D"
    )
    assert block.to_csv() == "blockcopy(TXT1..TXT2,TXT11..TXT12,oneshot=1,termination_code=$0D)"


# ---------------------------------------------------------------------------
# Block Copy of TXT into a number register
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dest", [("DS1", "DS2"), ("DD1", "DD2"), ("DH1", "DH2")])
def test_a_block_of_txt_into_a_number_needs_value_or_ascii(dest: tuple[str, str]) -> None:
    """CLICK's dialog saves a TXT range copied into DS, DD or DH with Copy Character Value,
    as in ``blockcopy(TXT1..TXT2,DS1..DS2,convert=to_value)``. A plain Block Copy of this
    kind is refused. ``convert=to_ascii`` is accepted too."""
    [error] = _errors(lambda: BlockCopy("TXT1", "TXT2", *dest))
    assert error.fields == ("BlockCopy.convert", "BlockCopy.source_start", "BlockCopy.dest_start")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)
    assert "convert=to_value" in str(error) and "convert=to_ascii" in str(error)
    for fmt, conv in (("to_value", "5"), ("to_ascii", "6")):
        block = BlockCopy("TXT1", "TXT2", *dest, convert=fmt)
        assert _tags(block.build_blob())[0x2227] == conv
        assert parse_af_blob(block.build_blob()) == block


def test_a_bare_block_of_txt_into_a_number_is_refused_from_csv(tmp_path: Path) -> None:
    with pytest.raises(FieldError, match="needs convert=to_value"):
        _read_af(tmp_path, "blockcopy(TXT1..TXT2,DS1..DS2)")


def test_a_stored_plain_block_of_txt_into_a_number_keeps_its_refusal() -> None:
    """laddercodec 0.4.0 wrote a plain Block Copy of TXT1..TXT2 into DS1..DS2. Such a blob
    decodes as a Block Copy that keeps the refusal. While its fields are unchanged, the Block
    Copy writes the bytes that it was decoded from."""
    tags = {0x6074: "TXT1", 0x6075: "TXT2", 0x6076: "DS1", 0x6077: "DS2", 0x2223: "1"}
    blob = _build_blob("Copy", 0x2721, (*tags, 0x0000), [*tags.values(), ""])
    parsed = parse_af_blob(blob)
    assert isinstance(parsed, BlockCopy)
    assert parsed.convert is None
    [error] = refusals(parsed)
    assert error.fields == ("BlockCopy.convert", "BlockCopy.source_start", "BlockCopy.dest_start")
    assert parsed.build_blob() == blob


# ---------------------------------------------------------------------------
# Keywords in the CSV
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("copy(TXT1,DS1,convert=to_value,termination_code=none)", Copy("TXT1", "DS1", "to_value")),
        ("copy(TXT1,DS1,convert=to_ascii,termination_code=0)", Copy("TXT1", "DS1", "to_ascii")),
        ("copy(DS1,DS2,termination_code=none)", Copy("DS1", "DS2")),
        (
            "copy(DS1,TXT1,convert=to_text(suppress_zero=1,termination_code=$0D),"
            "termination_code=none)",
            Copy("DS1", "TXT1", "to_text", suppress_zero=True, termination_code="$0D"),
        ),
        (
            "blockcopy(DS1..DS2,DS11..DS12,termination_code=none)",
            BlockCopy("DS1", "DS2", "DS11", "DS12"),
        ),
        (
            "blockcopy(TXT1..TXT2,DS1..DS2,convert=to_value,termination_code=0)",
            BlockCopy("TXT1", "TXT2", "DS1", "DS2", "to_value"),
        ),
    ],
)
def test_no_termination_code_is_taken_by_any_copy(tmp_path: Path, token: str, expected) -> None:
    """Any Copy or Block Copy accepts ``termination_code=none`` or ``0``. Both mean that
    there is no termination code."""
    assert _read_af(tmp_path, token) == expected


@pytest.mark.parametrize(
    "token",
    [
        "copy(TXT1,TXT21,terminaton_code=$0D)",
        "copy(DS1,TXT1,convert=to_text,suppress_zero=1)",
        "blockcopy(TXT1..TXT2,TXT11..TXT12,terminaton_code=$0D)",
        "blockcopy(DS1..DS2,DS11..DS12,one_shot=1)",
    ],
)
def test_a_keyword_copy_does_not_take_is_refused(tmp_path: Path, token: str) -> None:
    """A keyword that a Copy does not accept raises, such as a misspelt one or
    ``suppress_zero`` outside ``to_text``. The reader must not drop the keyword and lose its
    value."""
    with pytest.raises(ValueError, match="does not support keyword argument"):
        _read_af(tmp_path, token)
    if token.startswith("copy("):
        with pytest.raises(ValueError, match="does not support keyword argument"):
            Copy.from_csv_token(token)


# ---------------------------------------------------------------------------
# Block Copy into YD; Receive FC01 from a register
# ---------------------------------------------------------------------------


#: Sources of a Block Copy into YD0 that CLICK's dialog refuses. For each one, CLICK reports
#: OBJ-004, "The entered address cannot be used in this instruction."
CLICK_BLOCK_INTO_YD = [("DS1", "DS2"), ("DH1", "DH2"), ("XD0", "XD1")]


@pytest.mark.parametrize("source", [*CLICK_BLOCK_INTO_YD, ("C1", "C2"), ("TXT1", "TXT2")])
def test_a_block_copy_into_yd_is_refused_with_obj_004(source: tuple[str, str]) -> None:
    """CLICK refuses a Block Copy into YD from DS, DH and XD as an address that the
    instruction can't use. laddercodec has refused it with OBJ-004 from any source since
    0.4.0."""
    errors = _errors(lambda: BlockCopy(*source, "YD0", "YD1"))
    [error] = [e for e in errors if e.field == "BlockCopy.dest_start"]
    assert (error.reason, error.click_id) == (Reason.BANK, "OBJ-004")


def test_a_single_copy_into_yd_is_accepted() -> None:
    Copy("DS1", "YD0")
    Copy("TXT1", "YD0", convert="to_value")


RTU = ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=1)


def _receive(**kw) -> Receive:
    args = dict(
        target=RTU, remote_start="DS1", dest="DS1", quantity=1,
        receiving="C100", success="C101", error="C102", exception_response="DS100",
    )  # fmt: skip
    return Receive(**{**args, **kw})


@pytest.mark.parametrize("remote", ["DS1", "DD1", "DH1", "TXT1"])
def test_receive_fc01_from_a_register_carries_obj_004(remote: str) -> None:
    """A Receive that reads a register address on the slave with FC01, such as DS1 into C1,
    is refused with OBJ-004. CLICK refuses it as an address that the instruction can't use."""
    errors = _errors(lambda: _receive(remote_start=remote, dest="C1", function_code=1))
    assert errors[0].fields == ("Receive.function_code", "Receive.remote_start")
    assert (errors[0].reason, errors[0].click_id) == (Reason.CONFLICT, "OBJ-004")


def test_receive_fc02_from_a_register_has_no_id() -> None:
    errors = _errors(lambda: _receive(function_code=2))
    assert (errors[0].reason, errors[0].click_id) == (Reason.CONFLICT, None)
