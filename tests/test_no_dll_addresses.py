"""Committed files carry no CLICK DLL addresses.

A citation names its evidence (an OBJ-xxx id, a Help topic, a capture, an arc.md ruling or
``DLL: <name>.dll, <dialog/field>``), never a location inside a CLICK DLL.  The rule is
:func:`laddercodec.operands.sources.dll_address`, the same one ``Src`` uses.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from laddercodec.operands.sources import ALLOWED_LONG_HEX, Src, SrcKind, dll_address

ROOT = Path(__file__).resolve().parents[1]

# path -> reason.  Keep empty.
ALLOWED: dict[str, str] = {}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def test_address_pattern_matches_the_forms_in_use() -> None:
    digits = "0aabb"  # built here so this file holds no address itself
    for text in (
        "0x100" + digits,
        "@100" + digits,
        "Inst_Search 100" + digits,
        "at 100" + digits,
        "range ..0x100" + digits,
        "Inst_RD 100" + digits + "h",
        "Inst_RD 100" + digits + "H",
    ):
        assert dll_address(text), text
    for text in ("0x8bc0", "0x271e", "0x0A60", "0x6fff", "0x10e", "0x1201", "+0x19", "x1000"):
        assert not dll_address(text), text


def test_long_hex_pattern_matches_six_digits_or_more() -> None:
    value = "0x5A" + "7B9B"
    assert dll_address(f"writer at {value}")
    assert dll_address(f"{value}/{value}")
    assert not dll_address("command IDs 0x8036/0x802D, tag 0x1201")
    assert not dll_address("0x12345")


def test_allowed_values_are_exact_and_explained() -> None:
    for value, reason in ALLOWED_LONG_HEX.items():
        assert value == value.upper() and len(value) >= 6, value
        assert dll_address("0x" + value) is None, value
        assert reason, value


def _scan(text: str) -> list[tuple[int, str]]:
    return [
        (number, line.strip()[:100])
        for number, line in enumerate(text.splitlines(), 1)
        if dll_address(line) is not None
    ]


# Built here so this file holds no address itself.
_FAKE = f"{(0x1000 << 16) + 0x1234:08x}"
_BASE = f"{0x1000 << 16:x}"
_DLL = "Inst_SD.dll"

#: (text, refused): each form the rule knows, and text that only looks like one.
FORMS = [
    (f"Inst_SD.dll 0x{_FAKE}", True),
    (f"Inst_SD.dll 0X{_FAKE.upper()}", True),
    (f"baseEx.dll @{_FAKE}", True),
    (f"Inst_SD.dll sub_{_FAKE}", True),
    (f"FUN_{_FAKE}", True),
    (f"LAB_{_FAKE}", True),
    (f"Inst_SD.dll {_FAKE}", True),
    (f"Inst_SD.dll {_FAKE}h", True),
    (f"Inst_SD.dll {_FAKE}H", True),
    (f"Inst_SD.dll 0x{_FAKE[:4]}_{_FAKE[4:]}", True),
    (f"mask 0x{_BASE}", True),
    (f"capture 0x{(0x1A2B << 16) + 0x3C4D:08X}.bin", True),
    (f"writer at 0x{(0x5A << 16) + 0x7B9B:X}", True),
    (f"{_DLL}+0x1234", True),
    (f"{_DLL} + 1234", True),
    (f"{_DLL}+6cb1h", True),
    (f"{_DLL}!0x1234", True),
    (f"{_DLL}:0x1234", True),
    ("Inst_SD.dll, Send local banks", False),
    ("Inst_Copy.dll + dialog", False),
    ("Inst_SD.dll + 2 fields", False),
    ("Inst_SD.dll + dead", False),
    ("Inst_SD.dll: Send local banks", False),
    ("CL195", False),
    ("OBJ-004", False),
    ("mask 0x3f", False),
    ("0xFFFFFFFF sentinel", False),
    (f"value {_FAKE}0", False),
    ("offset 0x6cb1 in Inst_SD.dll", False),  # out of scope: see _DLL_ADDRESS_RE
]


@pytest.mark.parametrize(("text", "refused"), FORMS, ids=[f[0] for f in FORMS])
def test_src_and_file_scan_agree(text: str, refused: bool) -> None:
    assert bool(_scan(text)) is refused
    if refused:
        with pytest.raises(ValueError, match="DLL address"):
            Src(SrcKind.DLL, text)
    else:
        assert Src(SrcKind.DLL, text).ref == text


def test_no_dll_addresses_in_tracked_files() -> None:
    hits = []
    for rel in _tracked_files():
        if rel in ALLOWED:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{rel}:{number}: {line}" for number, line in _scan(text)]
    assert not hits, "DLL or executable addresses in committed files:\n" + "\n".join(hits)
