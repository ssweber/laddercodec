"""decode warns with LegacyEncodingWarning on a flag field that is stored empty.

CLICK writes a flag on the clipboard as ``1`` or ``-1`` when it is set and ``0`` when it is
clear. An older laddercodec wrote a set flag with no value in a blob that it composed from
the tags of a program file. CLICK runs a flag that is stored empty as clear. laddercodec
reads it as set and warns.
"""

from __future__ import annotations

import pickle
import re
import warnings
from pathlib import Path

import pytest

from laddercodec import (
    Coil,
    Contact,
    Copy,
    LegacyEncodingWarning,
    Math,
    RefusedFieldWarning,
    Rung,
    decode,
    encode,
)
from laddercodec.instructions import RawInstruction, Tee
from laddercodec.legacy import empty_flag_findings
from laddercodec.operands.unchecked import refusals, stored_blob

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_GOLDEN = _FIXTURES / "coverage" / "golden"

#: A flag field (tag 0x11xx or 0x12xx, standard sentinel) that holds ``0``, ``1`` or ``-1``.
_FLAG = re.compile(rb"([\x00-\xff][\x11\x12]\xff\xff\xff\xff)(?:-\x00)?[01]\x00\x00\x00", re.S)
#: A flag field that is stored empty.
_EMPTY_FLAG = re.compile(rb"[\x00-\xff][\x11\x12]\xff\xff\xff\xff\x00\x00", re.S)


def _blank_flags(data: bytes) -> bytes:
    """Return *data* with every flag field stored empty."""
    return _FLAG.sub(lambda m: m.group(1) + bytes(2), data)


def _flag_field(tag: int, value: str) -> bytes:
    return tag.to_bytes(2, "little") + b"\xff" * 4 + (value + "\0").encode("utf-16le")


def _decode_recording(data: bytes):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = decode(data)
    legacy = [w.message for w in caught if issubclass(w.category, LegacyEncodingWarning)]
    return out, legacy


def _row() -> list[str]:
    return ["-"] * 31


#: Each flag field that decode reads, and a golden that holds it.
_FIELDS = [
    ("Contact.immediate", "cond__immediate"),
    ("Coil.immediate", "latch__immediate"),
    ("Coil.oneshot", "out__oneshot"),
    ("Copy.oneshot", "copy__oneshot"),
    ("Copy.termination_code", "copy__to_text_term"),
    ("BlockCopy.oneshot", "blockcopy__oneshot"),
    ("BlockCopy.termination_code", "copy__txt_options"),
    ("Fill.oneshot", "fill__oneshot"),
    ("Pack.oneshot", "pack_bits__oneshot"),
    ("Unpack.oneshot", "unpack_to_bits__oneshot"),
    ("Drum.jog_enabled", "drum__v4"),
    ("Drum.jump_enabled", "drum__v4"),
    ("ForLoop.oneshot", "forloop__oneshot"),
    ("Math.mode", "math__hex"),
    ("Math.oneshot", "math__oneshot"),
    ("Search.oneshot", "search__oneshot"),
    ("Search.continuous", "search__continuous"),
    ("Home.tag_11f5", "raw_instructions__home"),
    ("PositionMove.tag_11f5", "raw_instructions__position"),
    ("VelocityMove.tag_11f5", "raw_instructions__velocity"),
]


@pytest.mark.parametrize(("field", "golden"), _FIELDS)
def test_each_flag_field_stored_empty_warns(field, golden):
    """A flag field stored empty warns and names the field. The rungs encode with it set."""
    legacy = _blank_flags((_GOLDEN / f"{golden}.bin").read_bytes())
    rungs, found = _decode_recording(legacy)
    named = [w for w in found if w.instruction == field]
    read = "the flag is stored empty, so laddercodec reads it as "
    assert any(w.detail.startswith(read) for w in named), sorted({w.instruction for w in found})
    for w in named:
        assert w.token == ""
        # A termination code also sets the text flag (0x1201), which decode does not read.
        assert w.detail.startswith(read) or w.detail == (
            "the flag is stored empty, and encoding this rung again writes it set. "
            "CLICK runs it as clear."
        )
        assert f"{field}: {w.detail} Encode this rung again and paste it." in str(w)

    # Each flag that decode reads is written set, so the rungs decode again with no warning.
    again, none = _decode_recording(encode(rungs))
    assert none == []
    assert again == rungs


def test_warning_text():
    rung = Rung(conditions=[_row()], instructions=[Coil("Y001", oneshot=True)], comment=None)
    data = encode(rung)
    legacy = data.replace(_flag_field(0x11F8, "1"), _flag_field(0x11F8, ""))
    assert legacy != data
    (decoded,), found = _decode_recording(legacy)
    assert decoded == rung
    assert [str(w) for w in found] == [
        "rung 0: Coil.oneshot: the flag is stored empty, so laddercodec reads it as True. "
        "CLICK runs it as False. Encode this rung again and paste it."
    ]
    assert (found[0].instruction, found[0].token, found[0].rung) == ("Coil.oneshot", "", 0)


def test_warning_names_a_mode_by_its_values():
    """An empty hex flag reads as a hex Math, and the warning says what CLICK runs."""
    rung = Rung(
        conditions=[_row()],
        instructions=[Math(expression="DH1 + 1h", dest="DH2", mode="hex")],
        comment=None,
    )
    legacy = encode(rung).replace(_flag_field(0x11FE, "-1"), _flag_field(0x11FE, ""))
    (decoded,), found = _decode_recording(legacy)
    assert decoded == rung
    assert [(w.instruction, w.detail) for w in found] == [
        (
            "Math.mode",
            "the flag is stored empty, so laddercodec reads it as 'hex'. "
            "CLICK runs it as 'decimal'.",
        )
    ]


def test_a_kept_blob_is_encoded_with_the_flag_set():
    """A decoded instruction that keeps its blob encodes the empty flag as CLICK writes it.

    The Math holds refusals, so it keeps the blob that it was decoded from. In that blob,
    the flag is written ``-1``.
    """
    blob = Math(expression="DS1 + 1", dest="DS2").build_blob()
    legacy_blob = blob.replace(_flag_field(0x11FE, "0"), _flag_field(0x11FE, ""))
    assert legacy_blob != blob
    raw = RawInstruction(class_name="Math", blob=legacy_blob, part_count=1)
    data = encode(Rung(conditions=[_row()], instructions=[raw], comment=None))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        (decoded,), found = _decode_recording(data)
    math = decoded.instructions[0]
    assert isinstance(math, Math)
    assert math.mode == "hex"
    assert refusals(math)
    assert [w.instruction for w in found] == ["Math.mode"]
    kept = stored_blob(math)
    assert kept is not None
    assert _flag_field(0x11FE, "-1") in kept
    assert _EMPTY_FLAG.search(kept) is None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        again, none = _decode_recording(encode(decoded))
    assert none == []
    assert again == [decoded]


def _blank_flag(data: bytes, tag: int) -> bytes:
    """Return *data* with each field of the flag *tag* stored empty."""
    key = tag.to_bytes(2, "little")
    return _FLAG.sub(lambda m: m.group(1) + bytes(2) if m.group(1)[:2] == key else m.group(0), data)


#: Each flag that decode does not read but the encoder writes from another field, and a
#: golden that holds it set. The warning names the field, or the tag if no one field sets it.
_WRITTEN = [
    ("Send.sending", "", 0x120A, "send__tcp_click_coil"),
    ("Send.success", "", 0x1209, "send__tcp_click_coil"),
    ("Send.error", "", 0x120B, "send__tcp_click_coil"),
    ("Send.exception_response", "", 0x121A, "send__tcp_click_coil"),
    ("Receive.receiving", "", 0x120A, "receive__tcp_click_coil"),
    ("Receive.success", "", 0x1209, "receive__tcp_click_coil"),
    ("Receive.error", "", 0x120B, "receive__tcp_click_coil"),
    ("Receive.exception_response", "", 0x121A, "receive__tcp_click_coil"),
    ("OutVariant.immediate", "", 0x11F5, "out__v4"),
    ("OutVariant", "1246=", 0x1246, "out__v4"),
    ("OutVariant.maintained", "", 0x1247, "out__v4"),
    ("Copy.source", "", 0x1201, "copy__click_forms"),
    ("Copy.termination_code", "", 0x1201, "copy__txt_options"),
    ("BlockCopy.termination_code", "", 0x1201, "copy__txt_options"),
]


@pytest.mark.parametrize(("field", "token", "tag", "golden"), _WRITTEN)
def test_a_flag_that_the_encoder_writes_from_another_field_warns(field, token, tag, golden):
    """decode does not read the flag, but encoding the rung writes it set. That warns.

    The rungs encode with the flag set, so they decode again with no warning.
    """
    data = (_GOLDEN / f"{golden}.bin").read_bytes()
    legacy = _blank_flag(data, tag)
    assert legacy != data
    rungs, found = _decode_recording(legacy)
    named = [w for w in found if (w.instruction, w.token) == (field, token)]
    assert named, sorted({(w.instruction, w.token) for w in found})
    for w in named:
        assert w.detail == (
            "the flag is stored empty, and encoding this rung again writes it set. "
            "CLICK runs it as clear."
        )
    # decode reads no field from the flag. A contact's immediate flag (0x11F5) reads as set.
    assert [r.instructions for r in rungs] == [r.instructions for r in decode(data)]

    again, none = _decode_recording(encode(rungs))
    assert none == []
    assert again == rungs


def test_a_flag_written_from_another_field_is_set_in_a_kept_blob():
    """A Copy that holds a refusal keeps its blob, and the blob has the empty flag set.

    The Copy copies text to C1, which its checks refuse. Its text flag (0x1201) is stored
    empty, and the encoder writes it from the text source.
    """
    blob = Copy('"A"', "TXT1").build_blob()
    dest = b"\x76\x60\xff\xff\xff\xff"
    legacy_blob = blob.replace(
        dest + "TXT1\0".encode("utf-16le"), dest + "C1\0".encode("utf-16le")
    ).replace(_flag_field(0x1201, "-1"), _flag_field(0x1201, ""))
    assert _flag_field(0x1201, "") in legacy_blob
    raw = RawInstruction(class_name="Copy", blob=legacy_blob, part_count=1)
    data = encode(Rung(conditions=[_row()], instructions=[raw], comment=None))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        (decoded,), found = _decode_recording(data)
    copy = decoded.instructions[0]
    assert isinstance(copy, Copy)
    assert copy.dest == "C1"
    assert refusals(copy)
    assert [w.instruction for w in found] == ["Copy.source"]
    kept = stored_blob(copy)
    assert kept is not None
    assert _flag_field(0x1201, "-1") in kept
    assert _EMPTY_FLAG.search(kept) is None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        again, none = _decode_recording(encode(decoded))
    assert none == []
    assert again == [decoded]


@pytest.mark.parametrize(
    ("tag", "golden"),
    [(0x121B, "receive__tcp_click_coil"), (0x1220, "send__tcp_click_coil"), (0x1201, "fill__tag")],
)
def test_a_flag_that_the_encoder_writes_clear_gives_no_warning(tag, golden):
    """decode does not read the flag, and the encoder writes it ``0``, as CLICK runs it."""
    data = (_GOLDEN / f"{golden}.bin").read_bytes()
    legacy = _blank_flag(data, tag)
    assert legacy != data
    rungs, found = _decode_recording(legacy)
    assert found == []
    assert rungs == decode(data)
    assert encode(rungs) == data


def test_a_contact_in_a_tee_warns():
    """decode warns for the contact that a Tee holds."""
    tee = Tee(Contact("X001", immediate=True))
    rung = Rung(
        conditions=[["-", tee, *["-"] * 29], ["", *["-"] * 30]],
        instructions=[Coil("Y001"), Coil("Y002")],
        comment=None,
    )
    data = encode(rung)
    legacy = _blank_flag(data, 0x11F5)
    assert legacy != data
    (decoded,), found = _decode_recording(legacy)
    assert decoded.conditions[0][1] == tee
    contacts = [w for w in found if w.instruction.startswith("Contact.")]
    assert [(w.instruction, w.rung) for w in contacts] == [("Contact.immediate", 0)]


def test_no_capture_holds_an_empty_flag():
    """CLICK writes every flag on the clipboard as ``1``, ``-1`` or ``0``.

    No clipboard file under tests/fixtures holds a flag field that is stored empty.
    """
    scanned = 0
    for path in sorted(_FIXTURES.rglob("*.bin")):
        data = path.read_bytes()
        if data[:8] != b"CLICK   ":
            continue
        scanned += 1
        assert _EMPTY_FLAG.search(data) is None, path
    assert scanned >= 300


def test_warning_with_no_token_survives_pickle():
    w = LegacyEncodingWarning("Copy.oneshot", "", "detail.", rung=1, program="P")
    assert (
        str(w) == "program 'P', rung 1: Copy.oneshot: detail. Encode this rung again and paste it."
    )
    clone = pickle.loads(pickle.dumps(w))
    assert (clone.instruction, clone.token, clone.rung, clone.program) == (
        "Copy.oneshot",
        "",
        1,
        "P",
    )
    assert str(clone) == str(w)


def test_a_flag_whose_clear_form_does_not_build_names_the_tag():
    """If the instruction can't be built with the flag clear, the finding names the tag."""
    coil = Coil("Y001", oneshot=True)
    found = empty_flag_findings(coil, 0x11F8, {0x11F8: ""}, lambda tags: None)
    assert found == [
        (
            "Coil",
            "11f8=",
            "the flag is stored empty, so laddercodec reads it as set. CLICK runs it as clear.",
        )
    ]
