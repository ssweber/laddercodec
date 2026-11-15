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
    a = _doc({"k": _refused("FieldError", "old", warn=["W: old"], write_warn=["V: old"])})
    b = _doc({"k": _refused("FieldError", "new", warn=["W: new"], write_warn=["V: new"])})
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


@pytest.mark.parametrize("key", ["warn", "write_warn"])
def test_tiers_fail_on_a_warning_class_change(tmp_path: Path, key: str) -> None:
    a = _doc({"k": {"new": "ok", key: ["LegacyEncodingWarning: m"]}})
    b = _doc({"k": {"new": "ok", key: ["UserWarning: m"]}})
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


#: Options every entry in these tests carries.
_ENTRY = "family=bits | kind=a"


def test_tiers_take_an_expected_entry(tmp_path: Path) -> None:
    a = _doc({"Copy/s/source='DS[1]'": {"new": "ok"}, "other": {"new": "ok"}})
    b = _doc({"Copy/s/source='DS[1]'": _refused("FieldError", "m"), "other": {"new": "ok"}})
    expected = (
        f"# comment\n\nCopy/*/source='DS[1]' | {_ENTRY} | a pointer index is a DS address\n"
        f"none | {_ENTRY} | unused\n"
    )
    status, out = _tiers(tmp_path, a, b, expected)
    assert status == 0, out
    assert f"Copy/*/source='DS[1]' | {_ENTRY} | a pointer index is a DS address" in out
    assert "match no difference: 1" in out
    assert "0 failure(s), 1 expected" in out


def test_an_entry_with_keys_allows_those_keys_only(tmp_path: Path) -> None:
    a = _doc({"k": {"new": "ok", "blob": "aaaa"}})
    entry = f"k | {_ENTRY} | keys=new,errors | the verdict changes\n"
    same_bytes = _doc({"k": _refused("FieldError", "m", blob="aaaa")})
    assert _tiers(tmp_path, a, same_bytes, entry)[0] == 0
    new_bytes = _doc({"k": _refused("FieldError", "m", blob="bbbb")})
    status, out = _tiers(tmp_path, a, new_bytes, entry)
    assert status == 1, out
    assert "~ k.blob" in out


def test_an_entry_with_keys_does_not_allow_an_added_case(tmp_path: Path) -> None:
    a = _doc({"other": {"new": "ok"}})
    b = _doc({"other": {"new": "ok"}, "k": {"new": "ok"}})
    assert _tiers(tmp_path, a, b, f"k | {_ENTRY} | keys=new | r\n")[0] == 1
    assert _tiers(tmp_path, a, b, f"k | {_ENTRY} | r\n")[0] == 0


@pytest.mark.parametrize(("pin", "status"), [("!FieldError", 0), ("!AddressError", 1), ("ok", 1)])
def test_an_entry_with_new_allows_that_verdict_only(tmp_path: Path, pin: str, status: int) -> None:
    a = _doc({"k": {"new": "ok"}})
    b = _doc({"k": _refused("FieldError", "m")})
    entry = f"k | {_ENTRY} | new={pin} | the value is refused\n"
    assert _tiers(tmp_path, a, b, entry)[0] == status


@pytest.mark.parametrize(
    ("pin", "read", "dec", "status"),
    [
        ("ok", "=", "=", 0),
        ("ok", "!FieldError", "=", 1),
        ("ok", "=", "None", 1),
        ("!FieldError", "!FieldError", "None", 0),
        ("!FieldError", "!ValueError", "None", 1),
        ("!FieldError", "!FieldError", "!ValueError", 1),
    ],
)
def test_a_pin_needs_read_and_dec_to_agree(
    tmp_path: Path, pin: str, read: str, dec: str, status: int
) -> None:
    a = _doc({"k": _refused("ValueError", "m", read="!ValueError", dec="!ValueError")})
    b = _doc({"k": {"new": pin, "read": read, "dec": dec}})
    entry = f"k | family=data | kind=b | new={pin} | r\n"
    assert _tiers(tmp_path, a, b, entry)[0] == status


def test_an_entry_with_new_does_not_allow_a_removed_case(tmp_path: Path) -> None:
    a = _doc({"k": {"new": "ok"}, "other": {"new": "ok"}})
    b = _doc({"other": {"new": "ok"}})
    assert _tiers(tmp_path, a, b, f"k | {_ENTRY} | new=ok | r\n")[0] == 1


#: A probe record of a value the base crashed on.
_CRASH = _refused("ValueError", "too many digits", read="!ValueError", tag="606a !ValueError")


def test_a_crash_entry_covers_crashes(tmp_path: Path) -> None:
    a = _doc({"Timer/on/setpoint='9'": _CRASH})
    b = _doc({"Timer/on/setpoint='9'": {"new": "ok", "read": "=", "csv": "x", "tag": "606a x"}})
    entry = "Timer/*/setpoint='9' | family=data | kind=b | new=ok | the set point is 9\n"
    status, out = _tiers(tmp_path, a, b, entry)
    assert status == 0, out
    assert "0 failure(s), 1 expected" in out


@pytest.mark.parametrize(
    "base",
    [
        _refused("FieldError", "a verdict"),
        _refused("AddressError", "a verdict"),
        {"new": "ok", "csv": "y"},
        {"csv": "no constructor verdict"},
        {**_CRASH, "read": "!FieldError"},  # the crash, but read gave a verdict
    ],
)
def test_tiers_refuse_a_crash_entry_used_on_a_verdict(tmp_path: Path, base: dict[str, Any]) -> None:
    # The entry allows the crash on "on" and is used on the verdict on "off": a misuse.
    branch = {"new": "ok", "read": "=", "csv": "x"}
    a = _doc({"Timer/on/setpoint='9'": _CRASH, "Timer/off/setpoint='9'": base})
    b = _doc({"Timer/on/setpoint='9'": branch, "Timer/off/setpoint='9'": branch})
    entry = "Timer/*/setpoint='9' | family=data | kind=b | new=ok | r\n"
    status, out = _tiers(tmp_path, a, b, entry)
    assert status == 2, out
    problems = out.split("cannot cover", 1)[1]
    assert "Timer/off/setpoint='9': line 1: Timer/*/setpoint='9': the base" in problems
    assert "Timer/on/setpoint" not in problems


def test_a_crash_entry_over_an_unchanged_verdict_is_unused(tmp_path: Path) -> None:
    # The family's change has not landed, or has landed in the base: the entry is unused.
    doc = _doc({"Timer/off/setpoint='9'": _refused("FieldError", "a verdict")})
    entry = "Timer/*/setpoint='9' | family=data | kind=b | new=ok | r\n"
    status, out = _tiers(tmp_path, doc, doc, entry)
    assert status == 0, out
    assert "match no difference: 1" in out


def test_a_crash_entry_does_not_allow_an_added_case(tmp_path: Path) -> None:
    a = _doc({"other": {"new": "ok"}})
    b = _doc({"other": {"new": "ok"}, "A/b/x='9'": {"new": "ok"}})
    status, out = _tiers(tmp_path, a, b, "A/b/x=* | family=bits | kind=b | new=ok | r\n")
    assert status == 1, out
    assert "1 failure(s), 0 expected" in out


def test_a_kind_a_entry_may_cover_a_verdict(tmp_path: Path) -> None:
    a = _doc({"k": _refused("FieldError", "m")})
    b = _doc({"k": {"new": "ok"}})
    assert _tiers(tmp_path, a, b, "k | family=move | kind=a | CLICK takes it\n")[0] == 0


@pytest.mark.parametrize(
    ("pattern", "key", "matches"),
    [
        ("Timer/*/setpoint='1'", "Timer/on/setpoint='1'", True),
        ("Timer/*='1'", "Timer/on/setpoint='1'", False),  # * stops at /
        ("Copy/*/source='DS*'", "Copy/c/source='DS1/2'", False),
        (r"Math/*/formula='DS1\*2'", "Math/m/formula='DS1*2'", True),
        (r"Math/*/formula='DS1\*2'", "Math/m/formula='DS1+2'", False),
        (r"Timer/*/setpoint='0'\*5000+'1'", "Timer/on/setpoint='0'*5000+'1'", True),
        (r"a\\b", "a\\b", True),
        (r"Copy/c/source='\xe9'", "Copy/c/source='\\xe9'", True),
        ("Copy/c/source='DS[DS1]'", "Copy/c/source='DS[DS1]'", True),
    ],
)
def test_an_entry_key_matches_whole(pattern: str, key: str, matches: bool) -> None:
    assert _identity_diff().Expected(1, pattern, "r", "bits", "a").matches(key) is matches


@pytest.mark.parametrize(
    "line",
    [
        "no reason here",
        f"key | {_ENTRY} | ",
        f" | {_ENTRY} | reason",
        "key | reason",  # no family, no kind
        "key | kind=a | reason",  # no family
        "key | family=bits | reason",  # no kind
        "key | family=math | kind=a | reason",
        "key | family=bits | kind=c | reason",
        "key | family=bits | family=data | kind=a | reason",
        f"key | {_ENTRY} | colour=red | reason",
        f"key | {_ENTRY} | keys= | reason",
        f"key | {_ENTRY} | keys=a,,b | r",
        f"key | {_ENTRY} | new= | r",
        "key | family=bits | kind=b | reason",  # a crash entry without new=
        "key | family=bits | kind=b | new=ok",  # no reason: new=ok is not one
        f"key | {_ENTRY} | keys=new",
    ],
)
def test_tiers_refuse_a_malformed_expected_file(tmp_path: Path, line: str) -> None:
    status, out = _tiers(tmp_path, _doc({"k": 1}), _doc({"k": 1}), line + "\n")
    assert status == 2, out
    assert "cannot read the expected-diff file" in out


def test_the_committed_expected_file_reads() -> None:
    # It may be empty: the last family to merge removes the last entries.
    entries = _identity_diff().read_expected(DEVTOOLS / "expected_diff.txt")
    assert all(entry.reason for entry in entries)
    assert all(entry.new for entry in entries if entry.kind == "b")


def test_the_dry_run_finds_no_difference() -> None:
    result = _run("classify_dryrun.py", SRC)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr
    assert "0 failure(s)" in result.stdout


def _patched(factory: pytest.TempPathFactory, name: str, old: str, new: str) -> Path:
    """A copy of ``src`` with ``old`` replaced by ``new`` in Compare's operand check."""
    src = factory.mktemp(name) / "src"
    shutil.copytree(
        SRC / "laddercodec", src / "laddercodec", ignore=shutil.ignore_patterns("__pycache__")
    )
    path = src / "laddercodec" / "instructions" / "comparison.py"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")
    return src


@pytest.fixture(scope="module")
def compare_wired_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compare reads a long run of leading zeros as the shared check does: the bits branch."""
    return _patched(
        tmp_path_factory,
        "compare_wired",
        "_INTEGER_MIN <= int(value) <= _INTEGER_MAX",
        '_INTEGER_MIN <= int(re.sub(r"^([+-]?)0+(?=[0-9])", r"\\1", value)) <= _INTEGER_MAX',
    )


@pytest.fixture(scope="module")
def compare_misread_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compare refuses a long run of leading zeros with a FieldError: not the shared verdict."""
    return _patched(
        tmp_path_factory,
        "compare_misread",
        'len(value.lstrip("+-").lstrip("0"))',
        'len(value.lstrip("+-"))',
    )


def test_a_family_branch_uses_its_entries(compare_wired_src: Path, tmp_path: Path) -> None:
    # Against the unwired base, --tiers allows the ten Compare crash cases by their entries.
    base, branch = tmp_path / "base.json", tmp_path / "branch.json"
    for src, out in ((SRC, base), (compare_wired_src, branch)):
        result = _run("operand_probe.py", src, out, "--classes", "CompareContact")
        assert result.returncode == 0, result.stdout + result.stderr
    tiers = _run("identity_diff.py", "--tiers", base, branch)
    assert tiers.returncode == 0, tiers.stdout[-3000:] + tiers.stderr
    assert "0 failure(s), 10 expected, 0 message-only" in tiers.stdout
    assert "CompareContact/ds/left='0'\\*5000+'1' | family=bits | kind=b | new=ok" in tiers.stdout

    # The dry run of the branch finds Compare agreeing; the bits entries are unused there.
    dry = _run("classify_dryrun.py", compare_wired_src)
    assert dry.returncode == 0, dry.stdout[-3000:] + dry.stderr
    assert "0 failure(s), 13 expected" in dry.stdout


def test_the_dry_run_refuses_a_crash_entry_used_on_a_verdict(compare_misread_src: Path) -> None:
    # Today refuses '0'*5000+'1' with a FieldError where the shared check accepts it: a real
    # difference, and the crash entry that matches it does not cover a verdict.
    dry = _run("classify_dryrun.py", compare_misread_src)
    assert dry.returncode == 2, dry.stdout[-3000:] + dry.stderr
    assert (
        "CompareContact/ds/right='0'*5000+'1': line " in dry.stderr
        and "the base gives new='!FieldError', not a crash" in dry.stderr
    )
