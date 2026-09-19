"""Compare native Java clipboard data with independently saved project XML."""

import importlib.util
from pathlib import Path

from laddercodec.productivity import decode_program, decode_project

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/productivity/two-button-latch"


def test_native_clipboard_cells_match_both_project_versions():
    spec = importlib.util.spec_from_file_location(
        "productivity_java_reader", ROOT / "devtools/productivity/read_java_stream.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = (FIXTURES / "rung-4.7.2.4.clipboard.bin").read_bytes()
    reader = module.Reader(data)
    assert reader.take(4) == bytes.fromhex("aced0005")
    root = reader.read()
    assert reader.pos == len(data) == 6709
    assert len(reader.handles) == 180

    def field(obj, suffix):
        return reader.resolve(next(v for k, v in obj["fields"].items() if k.endswith("." + suffix)))

    def vector(obj):
        return field(obj, "elementData")["values"][: field(obj, "elementCount")]

    native = decode_project((FIXTURES / "project-4.7.2.4.adpro").read_bytes())
    sources = [native.read("task/T1.rll"), (FIXTURES / "legacy-3.12.1/task/T1.rll").read_bytes()]
    clipboard_rows = vector(field(root, "bue"))
    assert len(clipboard_rows) == 2
    for source in sources:
        rows = {(r.number, r.subrung): r for r in decode_program(source).rungs}
        total = 0
        for row_ref in clipboard_rows:
            row = reader.resolve(row_ref)
            actual = {}
            for index, cell_ref in enumerate(vector(field(row, "flS"))):
                cell = reader.resolve(cell_ref)
                if cell is None:
                    continue
                instruction = field(cell, "gV")
                name = (
                    instruction["class"].split(".")[-1].replace("_", "").lower()
                    if instruction
                    else None
                )
                actual[index] = (field(cell, "flJ"), field(cell, "flK"), name)
            expected = rows[field(row, "flQ"), field(row, "flR")]
            cells = {
                p: (
                    e.element_type,
                    e.subtype,
                    e.instruction.kind.lower() if e.instruction else None,
                )
                for e in expected.elements
                for p in e.positions
            }
            assert actual == cells
            assert field(row, "aEL") == expected.comment
            total += len(actual)
        assert total == 29
