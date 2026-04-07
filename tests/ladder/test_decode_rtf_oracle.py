"""Oracle tests for RTF comment decoding."""

from __future__ import annotations

import re

import pytest
from striprtf.striprtf import rtf_to_text

from laddercodec.decode import _decode_rtf
from laddercodec.encode import _PREFIX, _SUFFIX
from tests.golden_io import GOLDEN_DIR

_REAL_FIXTURES = (
    "cmt-1row-fullwire-nop.bin",
    "cmt-1row-styled-mixed.bin",
    "instr-6row-multi-output.bin",
    "mr-cmt-2rung-2row.bin",
)


def _strip_markdown_markers(text: str) -> str:
    return text.replace("**", "").replace("__", "").replace("*", "")


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_fixture_rtf_payloads(name: str) -> list[bytes]:
    data = (GOLDEN_DIR / name).read_bytes()
    payloads: list[bytes] = []
    start = 0

    while True:
        idx = data.find(b"{\\rtf1", start)
        if idx == -1:
            break

        end = data.find(b"\x00", idx)
        if end == -1:
            break

        payload = data[idx : end + 1]
        if b"\\par }" in payload:
            payloads.append(payload)
        start = end + 1

    if not payloads:
        raise AssertionError(f"No RTF payloads found in fixture {name}")

    return payloads


def _oracle_payloads() -> list[object]:
    params: list[object] = []

    for name in _REAL_FIXTURES:
        for idx, payload in enumerate(_extract_fixture_rtf_payloads(name)):
            params.append(pytest.param(payload, id=f"real-{name}-rtf{idx}"))

    synthetic_cases = (
        ("synthetic-nested-groups", _PREFIX + rb"{\b Outer {\i inner} tail}" + _SUFFIX),
        (
            "synthetic-fonttbl-destination",
            _PREFIX + rb"{\*\fonttbl{\f0 Arial;}}Visible" + _SUFFIX,
        ),
        ("synthetic-cp1252-quotes", _PREFIX + rb"Quote: \'93Hello\'94" + _SUFFIX),
        ("synthetic-empty-bold-group", _PREFIX + rb"left {\b} right" + _SUFFIX),
        ("synthetic-unicode-ascii-fallback", _PREFIX + rb"\u8217?" + _SUFFIX),
        ("synthetic-unicode-hex-fallback", _PREFIX + rb"\u8217\'92" + _SUFFIX),
        ("synthetic-unicode-uc2", _PREFIX + rb"\uc2\u8217??" + _SUFFIX),
        ("synthetic-unicode-signed16", _PREFIX + rb"\u-24679?" + _SUFFIX),
    )
    params.extend(pytest.param(payload, id=case_id) for case_id, payload in synthetic_cases)
    return params


@pytest.mark.parametrize("payload", _oracle_payloads())
def test_decode_rtf_matches_striprtf_oracle(payload: bytes) -> None:
    ours = _normalize_whitespace(_strip_markdown_markers(_decode_rtf(payload)))

    rtf = payload[:-1] if payload.endswith(b"\x00") else payload
    oracle = _normalize_whitespace(rtf_to_text(rtf.decode("cp1252")))

    assert ours == oracle
