"""Native fixture bytes must survive checkout unchanged, including XML newlines."""

import hashlib
import json
from pathlib import Path


def test_native_fixture_hashes():
    fixtures = Path(__file__).resolve().parents[1] / "fixtures/productivity"
    provenance = json.loads((fixtures / "capture-provenance.json").read_text(encoding="utf-8"))
    for name, expected in provenance["native_files"].items():
        assert hashlib.sha256((fixtures / name).read_bytes()).hexdigest() == expected, name
