"""Smoke test for the behaviour-identity devtools (fixture snapshot, operand probe)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def _check_tool(script: str, limit: int, tmp_path: Path) -> dict:
    a, b = tmp_path / f"{script}.a.json", tmp_path / f"{script}.b.json"
    for out in (a, b):
        result = _run(script, SRC, out, "--limit", limit)
        assert result.returncode == 0, result.stderr
    same = _run(script, "--diff", a, b)
    assert same.returncode == 0, same.stdout
    assert "0 difference(s)" in same.stdout

    doc = json.loads(a.read_text(encoding="utf-8"))
    key = sorted(doc["cases"])[0]
    doc["cases"][key] = {"changed": True}
    b.write_text(json.dumps(doc), encoding="utf-8")
    changed = _run(script, "--diff", a, b)
    assert changed.returncode == 1
    assert key in changed.stdout
    return doc


def test_fixture_snapshot_is_deterministic(tmp_path: Path) -> None:
    doc = _check_tool("fixture_snapshot.py", 4, tmp_path)
    assert doc["meta"]["files"] == 4


def test_operand_probe_is_deterministic(tmp_path: Path) -> None:
    doc = _check_tool("operand_probe.py", 2, tmp_path)
    per_class = doc["meta"]["per_class"]
    assert per_class["Contact"]["cases"] == 2
    assert all(info["cases"] >= 1 for info in per_class.values())
    baseline = doc["cases"]["Contact/no/-"]
    assert baseline["new"] == "ok"
    assert baseline["read"] == "="
