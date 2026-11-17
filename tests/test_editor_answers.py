"""CLICK's answers to the editor grids, compared with laddercodec's rules.

``tests/fixtures/editor_grids/*.answers.json`` hold what CLICK's dialogs said to each case
(see that folder's README); they are never edited to fit the code.  Each answered case is
rebuilt here with the builders ``devtools/editor_grids.py`` uses and compared three ways:

- the outcome: CLICK accepted or refused, and so do the rules;
- the code: where both refuse and CLICK gave an ``OBJ-nnn``, the refusal's ``click_id`` is the
  same (a ``click_id`` of None is not a disagreement, and most refusals have none yet, so
  only some codes are compared: ``CODES_COMPARED`` is today's number, and a change that
  adds or drops ids changes it and fails); where one OK raised a chain of error boxes
  (``boxes``), ``code`` is the first;
- the save: an accepted case's ``stored`` rows read back with ``read_csv`` as an instruction
  that is not ``raw(...)``.

A case whose text is longer than its field's ``limits`` is skipped: the runner sets text by
WM_SETTEXT, which ignores the limit, so no user can type it.  The rule is the text length,
not the label.

``DISAGREEMENTS`` lists every difference, keyed by grid, case label and kind, with its reason
and the roadmap item that owns it.  The test fails on a difference not listed and on an entry
that no longer differs, as ``tests/test_operand_guards.py`` does for its allowlists.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from laddercodec import FieldError
from laddercodec.csv import read_csv
from laddercodec.decode_program import _scr_box
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.copy import BlockCopy, Copy, Pack, Unpack
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import RawInstruction, _decompose_blob
from laddercodec.instructions.send_receive import ModbusAddress, ModbusRtuTarget, Receive
from laddercodec.instructions.undecoded import Undecoded
from laddercodec.model import ADDRESS_BANKS, AfInstruction

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "tests" / "fixtures" / "editor_grids"

#: The files of cases CLICK answered, in the order they are compared.
ANSWER_FILES = (
    "preflight",
    "risky",
    "receive",
    "receive_count",
    "pickcheck",
    "picker_lists",
    "rule_rows",
    "out",
    "copy_single",
    "copy_block",
    "copy_pack",
    "copy_unpack",
    "math_decimal",
    "math_hex",
)

Key = tuple[str, str, str]  # (grid, case label or field, kind)

HEX_WORD = (
    "kept: laddercodec asks for the h; CLICK reads a word of hex digits typed without it as a "
    "hex constant, so 10 is 16 and DH0 is D0h (settled). A word shaped like an address (C0, "
    "DD0, DF0, DH0, DH501) is refused as outside its bank's range instead; to do: that "
    "message is to name the h form"
)
EDGE_SPACE = (
    "deliberate: CLICK accepts an edge space and the save trims it; an instruction holds the "
    "address in display form, so construction refuses the space"
)
EDGE_SPACE_KEPT = (
    "deliberate: CLICK accepts an edge space and the save keeps it; an instruction holds the "
    "address in display form, so construction refuses the space, and decode reads that save "
    "as the address without it"
)

# Copy (roadmap item 3, except where marked).
INNER_SPACE = (
    "kept: CLICK takes DS 1 (a space inside) as a Copy source or destination and as a Math "
    "result, and a Copy's save drops the space from the source and keeps it in the "
    "destination; an instruction holds the address in display form, so construction refuses "
    "the space, and read_csv refuses the save that keeps it (settled)"
)
SD_POINTER = (
    "to do: CLICK takes an SD pointer (SD[DS1]) as a Copy source and saves it as typed; the "
    "rules refuse it"
)
E_REAL = (
    "kept: laddercodec refuses; DS is an integer, so a real such as 0.0 or 1.0 is no source "
    "for a Copy into DS1, yet CLICK lets text that is not a number through as a real (E5 and "
    '"HELLO" are stored 0.0, 1E is 1.0); typing a valid constant can\'t make that rung, since '
    "0.0 into DS becomes 0 (settled)"
)
COPY_EH = (
    "kept: CLICK stores EH and 1Eh as the reals 0.0 and 1.0; laddercodec refuses them and names "
    "the forms to write, the real or the hex value as a decimal integer (settled)"
)
COPY_REAL_DIGITS = (
    "kept: CLICK keeps 7 significant digits and stores 3.4028235E+38 as 3.402823E+38, another "
    "value; laddercodec refuses a real of more than 7 and names the form CLICK stores (settled)"
)
RX2_COUNT = (
    "kept: the rx2 run recorded no count and the test takes 1, which CLICK refuses for TXT "
    "(OBJ-010); in the same setup the dialog holds 2 at OK (receive_count), which the rules "
    "accept; no answer says what rx2 held"
)


def _table(*groups: tuple[str, str, str, tuple[str, ...]]) -> dict[Key, str]:
    """One entry for each case of each group (reason, grid, kind, labels); a case listed twice
    fails, in one group or in two."""
    table: dict[Key, str] = {}
    for reason, grid, kind, labels in groups:
        for label in labels:
            key = (grid, label, kind)
            if key in table:
                raise ValueError(f"{key} is listed twice")
            table[key] = reason
    return table


#: Every difference between CLICK's answers and the rules.  Kinds: ``outcome`` (accepted or
#: refused), ``code`` (the OBJ id), ``stored`` (the save reads back as raw), ``list`` (the
#: writable SC or SD addresses).  Each group is one thing to do (or one kept on purpose).
DISAGREEMENTS: dict[Key, str] = _table(
    (RX2_COUNT, "receive", "outcome", ("03 -> TXT1",)),
    (
        EDGE_SPACE + " (Math result)",
        "risky",
        "outcome",
        ("dec  DS1 = DS2 + 1", "dec DS1  = DS2 + 1"),
    ),
    (
        EDGE_SPACE + " (Copy source)",
        "risky",
        "outcome",
        ("single  DS1 -> DS1", "single DS1  -> DS1"),
    ),
    (
        EDGE_SPACE_KEPT + " (Copy destination)",
        "risky",
        "outcome",
        ("single DS2 ->  DS1", "single DS2 -> DS1 "),
    ),
    (EDGE_SPACE + " (Block Copy source)", "risky", "outcome", ("block  DS1..DS2 -> DS11",)),
    (EDGE_SPACE_KEPT + " (Pack destination)", "risky", "outcome", ("pack C1..C16 ->  DS1",)),
    (EDGE_SPACE + " (Unpack source)", "risky", "outcome", ("unpack  DS1 -> C1..C16",)),
    (
        HEX_WORD,
        "preflight",
        "outcome",
        (
            "hex DH1 = 0",
            "hex DH1 = DH1 + 0",
            "hex DH1 = RAND(5,Ah)",
        ),
    ),
    (
        HEX_WORD,
        "math_hex",
        "outcome",
        (
            "hex DH1 = +0",
            "hex DH1 = +5",
            "hex DH1 = -0",
            "hex DH1 = -005",
            "hex DH1 = -5",
            "hex DH1 = 0",
            "hex DH1 = 005",
            "hex DH1 = 1-2",
            "hex DH1 = 1E39",
            "hex DH1 = 1E5",
            "hex DH1 = 1e5",
            "hex DH1 = 5",
            "hex DH1 = C0",
            "hex DH1 = C0 + 1h",
            "hex DH1 = DD0",
            "hex DH1 = DD0 + 1h",
            "hex DH1 = DF0",
            "hex DH1 = DF0 + 1h",
            "hex DH1 = DH0",
            "hex DH1 = DH0 + 1h",
            "hex DH1 = DH1 + 0",
            "hex DH1 = DH1 + 005",
            "hex DH1 = DH1 + 1-2",
            "hex DH1 = DH1 + 1E39",
            "hex DH1 = DH1 + 1E5",
            "hex DH1 = DH1 + 1e5",
            "hex DH1 = DH1 + 5",
            "hex DH1 = DH1 + E5",
            "hex DH1 = DH1 + abc",
            "hex DH1 = DH501",
            "hex DH1 = DH501 + 1h",
            "hex DH1 = E5",
            "hex DH1 = RAND(1h,5)",
            "hex DH1 = RAND(1h,C0)",
            "hex DH1 = RAND(1h,DD0)",
            "hex DH1 = RAND(1h,DF0)",
            "hex DH1 = RAND(1h,DH0)",
            "hex DH1 = RAND(1h,DH501)",
            "hex DH1 = RAND(5,Ah)",
            "hex DH1 = RAND(C0,Ah)",
            "hex DH1 = RAND(DD0,Ah)",
            "hex DH1 = RAND(DF0,Ah)",
            "hex DH1 = RAND(DH0,Ah)",
            "hex DH1 = RAND(DH501,Ah)",
            "hex DH1 = abc",
        ),
    ),
    (
        INNER_SPACE,
        "copy_single",
        "outcome",
        (
            "single DS 1 -> DS1",
            "single DS2 -> DS 1",
        ),
    ),
    (INNER_SPACE, "copy_single", "stored", ("single DS2 -> DS 1",)),
    (INNER_SPACE, "math_decimal", "outcome", ("dec DS 1 = DS2 + 1",)),
    (SD_POINTER, "copy_single", "outcome", ("single SD[DS1] -> DS1",)),
    (SD_POINTER, "copy_single", "stored", ("single SD[DS1] -> DS1",)),
    (
        E_REAL,
        "copy_single",
        "outcome",
        (
            'single "1E5" -> DS1',
            'single "E" -> DS1',
            'single "HELLO" -> DS1',
            'single "e" -> DS1',
            "single 1E -> DS1",
            "single E5 -> DS1",
        ),
    ),
    (COPY_EH, "copy_single", "outcome", ("single 1Eh -> DS1", "single EH -> DS1")),
    (COPY_REAL_DIGITS, "copy_single", "outcome", ("single 3.4028235E+38 -> DS1",)),
)

#: The codes compared today: both CLICK and the rules refuse, and the rules give a ``click_id``.
CODES_COMPARED = 2840


@pytest.fixture(scope="module")
def generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "editor_grids", ROOT / "devtools" / "editor_grids.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def compared(generator: Any) -> tuple[dict[Key, str], dict[str, int]]:
    """The comparison of every answer file, made once for the tests that read it."""
    return compare(generator)


def _answers(name: str) -> list[dict[str, Any]]:
    path = GRIDS / f"{name}.answers.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def too_long(case: dict[str, Any]) -> bool:
    """Whether the runner put in more text than the field takes: text no user can type."""
    return any(len(text) > case["limits"][name] for name, text in case["fields"].items())


def _receive(case: dict[str, Any]) -> object:
    """A Receive from a case, with the count the dialog held at OK (``read_back``).  A case
    with no recorded count (the rx2 file) is compared at quantity 1."""
    f = case["fields"]
    count = int(case["read_back"].get("count", 1))
    code = int(case["choices"]["function"].split(" ")[0])
    return Receive(
        target=ModbusRtuTarget(name="r", com_port="cpu2", device_id=1),
        remote_start=ModbusAddress(f["slave_address"]),
        dest=f["master_address"],
        quantity=count,
        receiving=f["receiving"],
        success=f["success"],
        error=f["error"],
        exception_response=f["exception"],
        function_code=code,
    )


def rules_verdict(generator: Any, case: dict[str, Any]) -> tuple[bool, str | None]:
    """Whether the rules accept the case, and the ``click_id`` of the refusal."""
    try:
        if case["instruction"] == "receive":
            _receive(case)
        else:
            seen: list[BaseException] = []

            def record(build: Any) -> dict[str, Any]:
                try:
                    build()
                except ValueError as exc:
                    seen.append(exc)
                    raise
                return {"verdict": "accepted"}

            original = generator.verdict_of
            generator.verdict_of = record
            try:
                generator.check_case(case)
            finally:
                generator.verdict_of = original
    except ValueError as exc:  # FieldError is one; any other exception fails the test
        return False, getattr(exc, "click_id", None)
    return True, None


def _read_rows(path: Path, rows: list[str]) -> list[Any]:
    """The rungs ``read_csv`` reads from *rows*, written to *path* under the header."""
    lines = ["marker," + ",".join(_columns()), *rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_csv(path)


def reads_as_raw(rows: list[str]) -> bool:
    """Whether the saved rung reads back as ``raw(...)`` (or an unknown condition).

    The rows were written by the laddercodec of the run from CLICK's program file; a
    ``raw(...)`` among them is read again from its tags, as ``decode_program`` reads that
    save today.  That laddercodec wrote ``to_text(suppress_zero=...)`` for a real constant,
    which now takes only ``exponential``; such a row is read without it.
    """
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "stored.csv"
        try:
            try:
                rungs = _read_rows(path, rows)
            except FieldError as exc:
                if exc.field != "Copy.suppress_zero":
                    raise
                rungs = _read_rows(path, [re.sub(r"suppress_zero=[01],", "", row) for row in rows])
        except Exception:
            return True
    return any(
        isinstance(i, Undecoded) or (isinstance(i, RawInstruction) and saved_box(i) is None)
        for r in rungs
        for i in r.instructions
    )


def saved_box(raw: RawInstruction) -> AfInstruction | None:
    """The box ``decode_program`` reads from the entry of a raw box it wrote, or None.

    That raw box holds the blob composed from the program file entry's tags: every tag a
    standard field, and a flag that is set an empty value.  So the box is read from those
    tags, its part rows and its cell rows, as ``decode_program`` reads the entry.
    """
    class_name, type_code, _parts, extra, fields = _decompose_blob(raw.blob)
    tags = {tag: value for tag, _sentinel, value in fields}
    part_rows = bytes([1, *(1 + row for row in extra)])
    cell_rows = bytes([raw.visual_rows or 0, raw.sub_rows or 0])
    box = _scr_box(class_name, type_code, tags, part_rows, {}, {}, cell_rows)
    return None if isinstance(box, RawInstruction) else box


def _columns() -> list[str]:
    letters = [chr(ord("A") + n) for n in range(26)] + ["AA", "AB", "AC", "AD", "AE"]
    return [*letters, "AF"]


def compare(generator: Any) -> tuple[dict[Key, str], dict[str, int]]:
    """Each difference found, by key, and the counts."""
    found: dict[Key, str] = {}
    counts = {"compared": 0, "skipped": 0, "codes": 0}
    for grid in ANSWER_FILES:
        for case in _answers(grid):
            if too_long(case):
                counts["skipped"] += 1
                continue
            counts["compared"] += 1
            # Picker checks are several cases per list: a difference is keyed by the row.
            label = case["row"] if grid == "pickcheck" else case["case"]
            accepted, click_id = rules_verdict(generator, case)
            clicks = case["outcome"] == "accepted"
            if case["outcome"] not in ("accepted", "refused") or clicks != accepted:
                found[(grid, label, "outcome")] = (
                    f"CLICK {case['outcome']}, rules accepted={accepted}"
                )
            elif not clicks and click_id is not None and case["code"].startswith("OBJ-"):
                counts["codes"] += 1
                if case["code"] != click_id:
                    found[(grid, label, "code")] = f"CLICK {case['code']}, rules {click_id}"
            if clicks and case.get("stored") and reads_as_raw(case["stored"]):
                found[(grid, label, "stored")] = f"saved as {case['stored']}"
    return found, counts


def _writable() -> list[dict[str, Any]]:
    path = GRIDS / "sc_sd_writable.answers.json"
    return json.loads(path.read_text(encoding="utf-8"))["fields"]


def _accepts_address(field: dict[str, Any], bank: str, number: int) -> bool:
    """Whether the rules accept the address ``bank`` + ``number`` in the picker's field, with the other
    fields as the picker had them (``filled``; a field left empty is tried with each source
    that could be there)."""
    address = f"{bank}{number}"
    filled = field.get("filled") or {}
    kind, mode = field["instruction"], field.get("mode")
    try:
        if kind == "out":
            Coil(address, range_end=None)
        elif mode == "single":
            Copy("DS1", address)
        elif mode == "block":
            BlockCopy("DS1", "DS2", address, f"{bank}{number + 1}")
        elif mode == "pack":
            sources = [(filled["source"], filled["source_end"])] if filled else PACK_SOURCES
            return any(_builds(_pack, s, e, address) for s, e in sources)
        elif mode == "unpack":
            sources = [filled["source"]] if filled else UNPACK_SOURCES
            as_end = field["field"] == "destination_end"
            return any(_builds(_unpack, s, bank, number, as_end) for s in sources)
        elif mode == "hex":
            Math("DH1", address, "hex")
        else:
            Math("DS2 + 1", address, "decimal")
    except Exception:
        return False
    return True


#: Sources a Pack or Unpack field may have when the picker was opened with nothing filled.
PACK_SOURCES = [("C1", "C16"), ("DS1", "DS2"), ("DD1", "DD2"), ("DH1", "DH2"), ("DF1", "DF2")]
UNPACK_SOURCES = ["DS1", "DD1", "DH1", "DF1"]


def _builds(build: Any, *args: Any) -> bool:
    try:
        build(*args)
    except Exception:
        return False
    return True


def _pack(source: str, end: str, address: str) -> object:
    bank = source.rstrip("0123456789")
    return Pack(source, end, address, "bits" if bank == "C" else "words")


def _unpack(source: str, bank: str, number: int, as_end: bool) -> object:
    """An Unpack whose destination range holds ``number`` as its start, or as its end."""
    if bank in ("C", "Y", "SC", "X"):
        length = 16
        kind = "bits"
    else:
        length = 2
        kind = "words"
    first = number - length + 1 if as_end else number
    last = number if as_end else number + length - 1
    if bank == "Y":
        return Unpack(source, f"Y{first:03d}", f"Y{last:03d}", kind)
    return Unpack(source, f"{bank}{first}", f"{bank}{last}", kind)


def compare_lists() -> dict[Key, str]:
    """Each field and bank whose writable list differs from the addresses the rules accept.
    A bank with no list (null: its tab is greyed) is an empty list, which the rules must match
    by accepting no address of that bank."""
    found: dict[Key, str] = {}
    for field in _writable():
        for bank in ("SC", "SD"):
            listed = set(field[bank] or [])
            lo, hi = ADDRESS_BANKS[bank]
            # A Block Copy needs the second address as well: the picker lists the start of a pair.
            accepted = {n for n in range(lo, hi + 1) if _accepts_address(field, bank, n)}
            wanted = listed
            if field.get("mode") == "block":
                numbers = {int(a[2:]) for a in listed}
                wanted = {f"{bank}{n}" for n in numbers if n + 1 in numbers}
            if {f"{bank}{n}" for n in accepted} != wanted:
                parts = [str(field[k]) for k in ("instruction", "mode", "field") if field.get(k)]
                name = ".".join(parts)
                if field.get("filled"):
                    name += " (after " + " ".join(field["filled"].values()) + ")"
                found[("sc_sd_writable", f"{name}.{bank}", "list")] = (
                    f"{len(accepted)} accepted, {len(wanted)} listed"
                )
    return found


#: The fields whose picker-check answers (the ``pickcheck`` file) follow the lists.
PICKER_CHECKED = {("out", None), ("copy", "single"), ("copy", "block"), ("math", "decimal")}


def compare_picker_checks() -> list[str]:
    """Picker-check answers that do not follow the list (a start in the list, and for a Block
    Copy the next address too, is accepted; an SC or SD outside its field's list is refused)."""
    lists = {
        (f["instruction"], f.get("mode")): {
            int(a[2:]) for a in f["SC" if f["instruction"] == "out" else "SD"]
        }
        for f in _writable()
        if (f["instruction"], f.get("mode")) in PICKER_CHECKED
    }
    wrong: list[str] = []
    for case in _answers("pickcheck"):
        f = case["fields"]
        key = (case["instruction"], case.get("mode"))
        target = f.get("destination") or f.get("result") or f["address"]
        bank_wanted = "SC" if case["instruction"] == "out" else "SD"
        if not target.startswith(bank_wanted):
            expected = False  # an SC address in a Copy: the field's tab is greyed
        else:
            number = int(target[2:])
            listed = lists[key]
            expected = number in listed and (key[1] != "block" or number + 1 in listed)
        if (case["outcome"] == "accepted") != expected:
            wrong.append(case["case"])
    return wrong


def test_answers_match_the_rules(compared: tuple[dict[Key, str], dict[str, int]]) -> None:
    found = dict(compared[0])
    found.update(compare_lists())
    assert set(found) - set(DISAGREEMENTS) == set(), (
        "a difference between CLICK's answers and the rules that DISAGREEMENTS does not list: "
        + "; ".join(f"{k}: {v}" for k, v in sorted(found.items()) if k not in DISAGREEMENTS)
    )
    assert set(DISAGREEMENTS) - set(found) == set(), (
        "DISAGREEMENTS lists a difference that is gone (remove it)"
    )


def test_picker_checks_follow_the_picker_lists() -> None:
    assert compare_picker_checks() == []


def test_the_length_rule_skips_what_cannot_be_typed(
    compared: tuple[dict[Key, str], dict[str, int]],
) -> None:
    _, counts = compared
    assert counts["skipped"] == 3, "RESULTS names three risky cases past their field's limit"
    skipped = [c["case"] for g in ANSWER_FILES for c in _answers(g) if too_long(c)]
    assert len(skipped) == 3


def test_every_case_was_answered() -> None:
    for grid in ANSWER_FILES:
        for case in _answers(grid):
            assert case["outcome"] in ("accepted", "refused"), (grid, case["case"])
            read_back = case["read_back"]
            if grid == "receive_count":
                # The dialog also held the Slave ID and, where a case left the count unset,
                # the count it defaults to.
                assert all(read_back[k] == v for k, v in case["fields"].items()), case["case"]
            else:
                assert read_back == case["fields"], (grid, case["case"])


def test_codes_compared_are_the_count(compared: tuple[dict[Key, str], dict[str, int]]) -> None:
    _, counts = compared
    assert counts["codes"] == CODES_COMPARED, counts


def test_a_case_listed_twice_fails() -> None:
    once = ("a reason", "out", "code", ("out C1..DS1",))
    with pytest.raises(ValueError, match="listed twice"):
        _table(once, ("another reason", "out", "code", ("out Y001..DS1", "out C1..DS1")))


def test_a_chain_of_boxes_starts_with_the_code() -> None:
    """Where one OK raised several error boxes (``boxes``, each a code and its message), the
    case's ``code`` and ``message`` are the first box's, and that code is the one compared."""
    chains = [
        (grid, case)
        for grid in ANSWER_FILES
        for case in _answers(grid)
        if case.get("boxes") is not None
    ]
    assert chains, "the copy_pack answers hold the chains of boxes"
    for grid, case in chains:
        assert case["outcome"] == "refused", (grid, case["case"])
        assert len(case["boxes"]) >= 2, (grid, case["case"])
        assert all(len(box) == 2 for box in case["boxes"]), (grid, case["case"])
        assert case["boxes"][0] == [case["code"], case["message"]], (grid, case["case"])


def test_answers_are_the_grids_cases() -> None:
    """The answered cases are the grid file's, label for label, with the same fields."""
    for grid in (
        "preflight",
        "risky",
        "out",
        "copy_single",
        "copy_block",
        "copy_pack",
        "copy_unpack",
        "math_decimal",
        "math_hex",
    ):
        cases = json.loads((GRIDS / f"{grid}.json").read_text(encoding="utf-8"))["cases"]
        answered = _answers(grid)
        assert [c["case"] for c in answered] == [c["case"] for c in cases], grid
        for case, answer in zip(cases, answered, strict=True):
            assert answer["fields"] == case["fields"], (grid, case["case"])
