"""Smoke test for the behaviour-identity devtools (fixture snapshot, operand probe)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DEVTOOLS = ROOT / "devtools"


def _run(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(DEVTOOLS / script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def _output(script: str, src: Path, out: Path, limit: int) -> dict[str, Any]:
    result = _run(script, src, out, "--limit", limit)
    assert result.returncode == 0, result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def _identity_diff() -> Any:
    spec = importlib.util.spec_from_file_location("identity_diff", DEVTOOLS / "identity_diff.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _narrowed(factory: pytest.TempPathFactory, banks: dict[str, tuple[int, int]]) -> Path:
    """A copy of ``src`` with ``banks`` replacing those banks' ranges in ``ADDRESS_BANKS``."""
    src = factory.mktemp("narrowed") / "src"
    shutil.copytree(
        SRC / "laddercodec", src / "laddercodec", ignore=shutil.ignore_patterns("__pycache__")
    )
    model = src / "laddercodec" / "model.py"
    lines = "".join(f"\nADDRESS_BANKS[{bank!r}] = {span!r}" for bank, span in banks.items())
    model.write_text(model.read_text(encoding="utf-8") + lines + "\n", encoding="utf-8")
    return src


@pytest.fixture(scope="module")
def narrowed_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Refuses C2000 and DS31 and above."""
    return _narrowed(tmp_path_factory, {"C": (1, 1999), "DS": (1, 30)})


@pytest.fixture(scope="module")
def c2000_refused_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Refuses C2000, which no probe baseline holds."""
    return _narrowed(tmp_path_factory, {"C": (1, 1999)})


@pytest.fixture(scope="module")
def drum_refused_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Refuses C187 and above: of the first baselines, only ``Drum/event`` holds one."""
    return _narrowed(tmp_path_factory, {"C": (1, 186)})


def _check_tool(script: str, limit: int, narrowed: Path, tmp_path: Path) -> dict[str, Any]:
    a, b, c = (tmp_path / f"{script}.{n}.json" for n in "abc")
    doc = _output(script, SRC, a, limit)
    _output(script, SRC, b, limit)
    same = _run(script, "--diff", a, b)
    assert same.returncode == 0, same.stdout + same.stderr
    assert "0 difference(s)" in same.stdout

    _output(script, narrowed, c, limit)
    changed = _run(script, "--diff", a, c)
    assert changed.returncode == 1, changed.stdout + changed.stderr
    return doc | {"narrowed_diff": changed.stdout}


def test_fixture_snapshot_sees_a_narrowed_bank(narrowed_src: Path, tmp_path: Path) -> None:
    doc = _check_tool("fixture_snapshot.py", 4, narrowed_src, tmp_path)
    assert doc["meta"]["files"] == 4
    assert "blockcopy__" in doc["narrowed_diff"]


def test_operand_probe_sees_a_narrowed_bank(c2000_refused_src: Path, tmp_path: Path) -> None:
    doc = _check_tool("operand_probe.py", 40, c2000_refused_src, tmp_path)
    per_class = doc["meta"]["per_class"]
    assert per_class["Contact"]["cases"] == 40
    assert all(info["cases"] >= 1 for info in per_class.values())
    assert doc["meta"]["refused_baselines"] == []
    baseline = doc["cases"]["Contact/no/-"]
    assert baseline["new"] == "ok"
    assert baseline["read"] == "="
    assert "~ Coil/out/operand='C2000'.new: \"ok\"" in doc["narrowed_diff"]


def test_operand_probe_fails_on_a_refused_baseline(drum_refused_src: Path, tmp_path: Path) -> None:
    refused = tmp_path / "refused.json"
    result = _run("operand_probe.py", drum_refused_src, refused, "--limit", 1)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "Drum/event" in result.stderr
    doc = json.loads(refused.read_text(encoding="utf-8"))
    assert doc["meta"]["refused_baselines"] == ["Drum/event"]
    assert doc["cases"]["Drum/event/-"]["new"] == "!AddressError"
    assert doc["cases"]["Drum/event/-"]["errors"][0][0] == "AddressError"

    good = tmp_path / "good.json"
    _output("operand_probe.py", SRC, good, 1)
    for a, b in ((good, refused), (refused, good), (refused, refused)):
        diff = _run("identity_diff.py", a, b)
        assert diff.returncode == 2, diff.stdout + diff.stderr
        assert "refused probe baseline(s) Drum/event" in diff.stderr


def test_outputs_of_different_tools_differ(tmp_path: Path) -> None:
    snap = tmp_path / "snap.json"
    probe = tmp_path / "probe.json"
    _output("fixture_snapshot.py", SRC, snap, 1)
    _output("operand_probe.py", SRC, probe, 1)
    result = _run("identity_diff.py", snap, probe)
    assert result.returncode == 1
    assert "tool differs" in result.stdout


def _doc(cases: Any, limit: int | None = None) -> dict[str, Any]:
    return {"tool": "t", "meta": {"scope": {"limit": limit}}, "cases": cases}


def _diff(tmp_path: Path, a: Any, b: Any) -> int:
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for path, doc in zip(paths, (a, b), strict=True):
        path.write_text(json.dumps(doc), encoding="utf-8")
    return _identity_diff().diff_files(*paths)


@pytest.mark.parametrize("other", [True, 1.0, "1", [1], None])
def test_identity_diff_counts_the_json_type(tmp_path: Path, other: Any) -> None:
    assert _diff(tmp_path, _doc({"k": {"v": 1}}), _doc({"k": {"v": other}})) == 1
    assert _diff(tmp_path, _doc({"k": {"v": 1}}), _doc({"k": {"v": 1}})) == 0


def test_identity_diff_refuses_outputs_it_cannot_compare(tmp_path: Path) -> None:
    assert _diff(tmp_path, _doc({"k": 1}, limit=2), _doc({"k": 1}, limit=None)) == 2
    assert _diff(tmp_path, _doc({}), _doc({})) == 2
    assert _diff(tmp_path, _doc({"k": 1}), {"tool": "t", "meta": {}}) == 2
    assert _diff(tmp_path, _doc({"k": 1}), [1, 2]) == 2


def _tiers(tmp_path: Path, a: Any, b: Any, expected: str = "") -> tuple[int, str]:
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for path, doc in zip(paths, (a, b), strict=True):
        path.write_text(json.dumps(doc), encoding="utf-8")
    entries = tmp_path / "expected.txt"
    entries.write_text(expected, encoding="utf-8")
    result = _run("identity_diff.py", "--tiers", "--expected", entries, *paths)
    return result.returncode, result.stdout + result.stderr


def _refused(cls: str, message: str, **more: Any) -> dict[str, Any]:
    """A probe record whose constructor refused, as the tools write it."""
    return {"new": f"!{cls}", "errors": [[cls, message]], **more}


def test_tiers_list_a_message_change_apart(tmp_path: Path) -> None:
    a = _doc({"k": _refused("FieldError", "old words", warn=["LegacyEncodingWarning: old"])})
    b = _doc({"k": _refused("FieldError", "new words", warn=["LegacyEncodingWarning: new"])})
    status, out = _tiers(tmp_path, a, b)
    assert status == 0, out
    assert "message wording only: 1 case(s)" in out
    assert "0 failure(s)" in out


@pytest.mark.parametrize(
    "b",
    [
        {"new": "ok"},  # a refusal became an accept
        _refused("AddressError", "same words"),  # the exception class changed
        _refused("FieldError", "row 1: AddressError: m"),  # a class the message names
        _refused("FieldError", "same words", warn=["UserWarning: x"]),  # a warning appears
    ],
)
def test_tiers_fail_on_a_verdict_or_class_change(tmp_path: Path, b: dict[str, Any]) -> None:
    a = _doc({"k": _refused("FieldError", "same words")})
    status, out = _tiers(tmp_path, a, _doc({"k": b}))
    assert status == 1, out
    assert "1 failure(s)" in out


def test_tiers_fail_on_a_warning_class_change(tmp_path: Path) -> None:
    a = _doc({"k": {"new": "ok", "warn": ["LegacyEncodingWarning: m"]}})
    b = _doc({"k": {"new": "ok", "warn": ["UserWarning: m"]}})
    assert _tiers(tmp_path, a, b)[0] == 1


def test_tiers_see_text_shaped_like_an_exception(tmp_path: Path) -> None:
    # Accepted text that holds "!A: " is data: a change after it is a CSV change.
    a = _doc({"Copy/s/source='\"!A: x\"'": {"new": "ok", "write": 'copy("!A: x",TXT1)'}})
    b = _doc({"Copy/s/source='\"!A: x\"'": {"new": "ok", "write": 'copy("!A: x",TXT2)'}})
    status, out = _tiers(tmp_path, a, b)
    assert status == 1, out
    assert "1 failure(s), 0 expected, 0 message-only" in out


def test_tiers_fail_on_an_added_case_and_other_fields(tmp_path: Path) -> None:
    a = _doc({"k": _refused("FieldError", "m", csv="x")})
    b = _doc({"k": _refused("FieldError", "m", csv="y"), "j": {"new": "ok"}})
    status, out = _tiers(tmp_path, a, b)
    assert status == 1, out
    assert "2 failure(s)" in out


def test_tiers_take_an_expected_entry(tmp_path: Path) -> None:
    a = _doc({"Copy/s/source='DS[1]'": {"new": "ok"}, "other": {"new": "ok"}})
    b = _doc({"Copy/s/source='DS[1]'": _refused("FieldError", "m"), "other": {"new": "ok"}})
    expected = (
        "# comment\n\nCopy/*/source='DS[1]' | a pointer index is a DS address\nnone | unused\n"
    )
    status, out = _tiers(tmp_path, a, b, expected)
    assert status == 0, out
    assert "Copy/*/source='DS[1]' | a pointer index is a DS address" in out
    assert "match no difference: 1" in out
    assert "0 failure(s), 1 expected" in out


def test_an_entry_with_keys_allows_those_keys_only(tmp_path: Path) -> None:
    a = _doc({"k": {"new": "ok", "blob": "aaaa"}})
    entry = "k | keys=new,errors | the verdict changes\n"
    same_bytes = _doc({"k": _refused("FieldError", "m", blob="aaaa")})
    assert _tiers(tmp_path, a, same_bytes, entry)[0] == 0
    new_bytes = _doc({"k": _refused("FieldError", "m", blob="bbbb")})
    status, out = _tiers(tmp_path, a, new_bytes, entry)
    assert status == 1, out
    assert "~ k.blob" in out


def test_an_entry_with_keys_does_not_allow_an_added_case(tmp_path: Path) -> None:
    a = _doc({"other": {"new": "ok"}})
    b = _doc({"other": {"new": "ok"}, "k": {"new": "ok"}})
    assert _tiers(tmp_path, a, b, "k | keys=new | r\n")[0] == 1
    assert _tiers(tmp_path, a, b, "k | r\n")[0] == 0


@pytest.mark.parametrize(
    ("pattern", "key", "matches"),
    [
        ("Timer/*/setpoint='1'", "Timer/on/setpoint='1'", True),
        (r"Math/*/formula='DS1\*2'", "Math/m/formula='DS1*2'", True),
        (r"Math/*/formula='DS1\*2'", "Math/m/formula='DS1+2'", False),
        (r"Timer/*/setpoint='0'\*5000+'1'", "Timer/on/setpoint='0'*5000+'1'", True),
        (r"a\\b", "a\\b", True),
        (r"Copy/c/source='\xe9'", "Copy/c/source='\\xe9'", True),
        ("Copy/c/source='DS[DS1]'", "Copy/c/source='DS[DS1]'", True),
    ],
)
def test_an_entry_key_matches_whole(pattern: str, key: str, matches: bool) -> None:
    assert _identity_diff().Expected(1, pattern, "r").matches(key) is matches


@pytest.mark.parametrize(
    "line", ["no reason here", "key | ", " | reason", "key | keys= | reason", "key | keys=a,,b | r"]
)
def test_tiers_refuse_a_malformed_expected_file(tmp_path: Path, line: str) -> None:
    status, out = _tiers(tmp_path, _doc({"k": 1}), _doc({"k": 1}), line + "\n")
    assert status == 2, out
    assert "cannot read the expected-diff file" in out


def test_the_committed_expected_file_reads() -> None:
    entries = _identity_diff().read_expected(DEVTOOLS / "expected_diff.txt")
    assert all(entry.reason for entry in entries)


def test_the_dry_run_finds_no_difference() -> None:
    result = _run("classify_dryrun.py", SRC)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr
    assert "0 failure(s)" in result.stdout
