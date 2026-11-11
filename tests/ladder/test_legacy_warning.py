"""LegacyEncodingWarning: decode warns on a Math constant stored as 16-bit past 16 bits."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from laddercodec import LegacyEncodingWarning, Math, Rung, decode, decode_program, encode

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _rung(expr: str) -> Rung:
    return Rung(
        logical_rows=1,
        conditions=[[""] * 31],
        instructions=[Math(expression=expr, result="DD1")],
        comment=None,
    )


def _u16(text: str) -> bytes:
    return text.encode("utf-16le")


def _decode_recording(data: bytes):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", LegacyEncodingWarning)
        out = decode(data)
    return out, [w.message for w in caught if issubclass(w.category, LegacyEncodingWarning)]


def test_w_form_gives_no_warning():
    data = encode(_rung("70000 + DS1"))
    assert _u16("W70000") in data
    _, found = _decode_recording(data)
    assert found == []


@pytest.mark.parametrize(
    ("current", "legacy", "token", "runs_as"),
    [("70000", "70000", "H70000", 4464), ("-40000", "-40000", "H-40000", 25536)],
)
def test_legacy_h_form_warns_and_decodes_the_same(current, legacy, token, runs_as):
    data = encode(_rung(f"{current} + DS1"))
    old = data.replace(_u16(f"W{legacy}"), _u16(f"H{legacy}"))
    assert old != data
    new_rung, none = _decode_recording(data)
    old_rung, found = _decode_recording(old)
    assert none == []
    assert old_rung == new_rung
    assert len(found) == 1
    w = found[0]
    assert (w.instruction, w.token, w.rung, w.program) == ("Math", token, 0, None)
    assert str(runs_as) in w.detail
    assert f"rung 0: Math {token}" in str(w)


def test_multi_rung_reports_rung_index():
    clean = _rung("DS1 + 1")
    bad = _rung("70000 + DS1")
    data = encode([clean, clean, bad, clean])
    old = data.replace(_u16("W70000"), _u16("H70000"))
    _, found = _decode_recording(old)
    assert [(w.rung, w.token) for w in found] == [(2, "H70000")]


def test_in_range_h_constant_gives_no_warning():
    _, found = _decode_recording(encode(_rung("32767 + DS1")))
    assert found == []


def test_decode_program_warns_with_program_name():
    path = _FIXTURES / "tumbler" / "subroutines" / "PLCDateTime.scr"
    data = path.read_bytes()
    old = data.replace(_u16("H10000"), _u16("H70000"))
    assert old != data
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", LegacyEncodingWarning)
        program = decode_program(old)
    found = [w.message for w in caught if issubclass(w.category, LegacyEncodingWarning)]
    assert found
    assert all(w.token == "H70000" and w.program == program.name for w in found)
    assert all(w.rung is not None and w.rung < len(program.rungs) for w in found)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        decode_program(data)
    assert not [w for w in caught if issubclass(w.category, LegacyEncodingWarning)]


def test_no_fixture_warns():
    """Every capture under tests/fixtures decodes without a legacy warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", LegacyEncodingWarning)
        for path in sorted(_FIXTURES.rglob("*.bin")):
            data = path.read_bytes()
            if data[:8] == b"CLICK   ":
                try:
                    decode(data)
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, LegacyEncodingWarning):
                        raise
        for path in sorted(_FIXTURES.rglob("*.scr")):
            try:
                decode_program(path.read_bytes())
            except LegacyEncodingWarning:
                raise
            except Exception:  # noqa: BLE001
                pass
