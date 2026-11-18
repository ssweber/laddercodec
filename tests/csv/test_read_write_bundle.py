"""Tests for ``write_bundle`` and ``read_bundle``: a ``Project`` as ``main.csv`` and
``subroutines/<name>.csv``."""

from __future__ import annotations

import copy
import csv
import pickle
import shutil
import warnings
from pathlib import Path

import pytest

import laddercodec.csv.bundle
from laddercodec import (
    CLICK_IDS,
    CSV_HEADER,
    AddressError,
    Code,
    Coil,
    Contact,
    CsvError,
    CsvLocation,
    FieldError,
    Program,
    Project,
    RefusedFieldWarning,
    Rung,
    WriterError,
    decode_program,
    read_bundle,
    read_csv,
    write_bundle,
    write_csv,
)
from laddercodec.csv.bundle import _in_bundle_order, _subroutine_names, parse_bundle
from laddercodec.instructions import Shift

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TUMBLER = FIXTURES / "tumbler"

#: A Timer that CLICK's dialog refuses: TD2 is not the accumulator of T1.
BAD_TIMER = "on_delay(T1,TD2,preset=40000,unit=Tms)"


def _rung(contact: str, coil: str) -> Rung:
    """Return a one-row rung with a contact on *contact* wired to an out coil on *coil*."""
    return Rung(
        conditions=[[Contact(contact), *["-"] * 30]], instructions=[Coil(coil)], comment=None
    )


def _unwritable_rung() -> Rung:
    """Return a rung that the CSV can't hold: a three-row Shift in a two-row rung."""
    blank = [""] * 31
    return Rung(conditions=[blank, blank], instructions=[Shift("C99", "C106"), ""], comment=None)


def _project(
    *names: str, main: tuple[str, str] = ("X1", "Y1"), sub: tuple[str, str] = ("C1", "Y2")
) -> Project:
    """Return a project whose main program and each subroutine named in *names* hold one
    rung.  *main* and *sub* are the contact and the coil of those rungs."""
    return Project(
        main=Program("Main Program", 1, [_rung(*main)]),
        subroutines=[Program(name, idx, [_rung(*sub)]) for idx, name in enumerate(names, start=2)],
    )


def _write_file(path: Path, *afs: str) -> Path:
    """Write a CSV file at *path* with one rung for each AF token in *afs*: ``X001`` wired
    to the token."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for af in afs:
            writer.writerow(["R", "X001", *["-"] * 30, af])
    return path


def _unreadable(path: Path) -> Path:
    """Write a file at *path* that is not UTF-8, so that reading it raises ``CsvError``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff")
    return path


def _read_rows(path: Path) -> list[list[str]]:
    """Return the rows of the CSV file at *path*."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Return every file and directory under *root*, with the bytes of each file."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
        for p in root.rglob("*")
    }


def _through_csv(rungs: list[Rung], stop: str, tmp: Path) -> list[Rung]:
    """Return *rungs* after ``write_csv`` writes them to one file and ``read_csv`` reads it."""
    path = tmp / "one.csv"
    write_csv(path, rungs, stop=stop)  # type: ignore[arg-type]
    return read_csv(path)


def _tumbler() -> Project:
    """Return the tumbler fixture as a project, with the subroutines in reverse file-name
    order and the ``prog_idx`` values that CLICK gave them."""
    main = decode_program((TUMBLER / "main.scr").read_bytes())
    subs = sorted((TUMBLER / "subroutines").glob("*.scr"), reverse=True)
    return Project(main=main, subroutines=[decode_program(p.read_bytes()) for p in subs])


class TestRoundTrip:
    def test_tumbler_reads_back_in_file_name_order(self, tmp_path: Path) -> None:
        """``read_bundle`` returns each program of the tumbler project with the rungs that
        one CSV file holds for it.  The subroutines come back sorted by name with case
        ignored, so the ``sm_`` names sort among the ``S`` names.  They are numbered from 2.

        ``write_csv`` and ``read_csv`` redraw two of the subroutines, AlmHistorian and
        WarnTimestamp, as CLICK's syntax check draws them.  So the test compares each
        program with the rungs that ``read_csv`` reads from its own ``write_csv`` file.
        """
        project = _tumbler()
        bundle = tmp_path / "bundle"
        write_bundle(bundle, project)
        back = read_bundle(bundle)

        ordered = sorted(project.subroutines, key=lambda p: p.name.casefold())
        names = [sub.name for sub in ordered]
        assert names.index("SFCExample") < names.index("sm_CopyOrJumpState")
        assert names.index("sm_StateComplete2Request") < names.index("ThermErrors")
        expected = Project(
            main=Program("Main Program", 1, _through_csv(project.main.rungs, "end", tmp_path)),
            subroutines=[
                Program(sub.name, idx, _through_csv(sub.rungs, "return", tmp_path))
                for idx, sub in enumerate(ordered, start=2)
            ],
        )
        assert back == expected
        assert len(back.subroutines) == 33
        changed = [
            sub.name
            for sub, read in zip(ordered, expected.subroutines, strict=True)
            if sub.rungs != read.rungs
        ]
        assert changed == ["AlmHistorian", "WarnTimestamp"]
        assert project.main.rungs == expected.main.rungs

    def test_each_file_is_what_write_csv_writes(self, tmp_path: Path) -> None:
        """Each file holds the bytes that ``write_csv`` writes for its program, with
        ``stop="end"`` for main and ``stop="return"`` for a subroutine.  ``index=True``
        numbers each file from ``R1``."""
        project = _tumbler()
        bundle = tmp_path / "bundle"
        write_bundle(bundle, project, index=True)

        one = tmp_path / "one.csv"
        write_csv(one, project.main.rungs, index=True, stop="end")
        assert (bundle / "main.csv").read_bytes() == one.read_bytes()
        for sub in project.subroutines:
            write_csv(one, sub.rungs, index=True, stop="return")
            path = bundle / "subroutines" / f"{sub.name}.csv"
            assert path.read_bytes() == one.read_bytes()
            first = next(row for row in _read_rows(path) if row[0].startswith("R"))
            assert first[0] == "R1"
        assert sorted(p.name for p in bundle.iterdir()) == ["main.csv", "subroutines"]

    def test_names_are_stripped(self, tmp_path: Path) -> None:
        write_bundle(tmp_path, _project("  Pump  "))
        assert [p.name for p in (tmp_path / "subroutines").iterdir()] == ["Pump.csv"]
        assert [sub.name for sub in read_bundle(tmp_path).subroutines] == ["Pump"]

    def test_no_subroutines(self, tmp_path: Path) -> None:
        """A project with no subroutines writes ``main.csv`` and an empty ``subroutines/``,
        and reads back the same."""
        project = _project()
        write_bundle(tmp_path / "new" / "bundle", project)
        assert _snapshot(tmp_path / "new" / "bundle").keys() == {"main.csv", "subroutines"}
        assert read_bundle(tmp_path / "new" / "bundle") == project

    def test_order_ignores_case(self, tmp_path: Path) -> None:
        """A sort that does not ignore case would put ``Beta`` and ``Zeta`` before
        ``alpha``."""
        write_bundle(tmp_path, _project("Zeta", "alpha", "Beta"))
        back = read_bundle(tmp_path)
        assert [(sub.name, sub.prog_idx) for sub in back.subroutines] == [
            ("alpha", 2),
            ("Beta", 3),
            ("Zeta", 4),
        ]

    def test_a_subroutine_named_main(self, tmp_path: Path) -> None:
        """``subroutines/main.csv`` holds the subroutine ``main``, not the main program."""
        project = _project("main", sub=("C2", "Y4"))
        write_bundle(tmp_path, project)
        assert read_bundle(tmp_path) == project
        parsed = parse_bundle(tmp_path)
        assert (parsed.main.role, parsed.main.subroutine_slug) == ("main", None)
        [sub] = parsed.subroutines
        assert (sub.path, sub.role, sub.subroutine_slug) == (
            tmp_path / "subroutines" / "main.csv",
            "subroutine",
            "main",
        )

    def test_dot_names(self, tmp_path: Path) -> None:
        """``.`` and ``..`` are written as ``..csv`` and ``...csv`` and read back."""
        write_bundle(tmp_path, _project("..", "."))
        written = sorted(p.name for p in (tmp_path / "subroutines").iterdir())
        if written != ["...csv", "..csv"]:
            pytest.skip(f"this file system stores the names as {written}")
        assert read_bundle(tmp_path) == _project(".", "..")


class TestOrder:
    """The order of the subroutine files, tested on paths in memory so that it does not
    depend on the file system."""

    def test_case_is_ignored_first(self) -> None:
        names = ["b.csv", "Zeta.CSV", "alpha.csv", "Beta.csv", "pump.csv", "Pump.csv"]
        ordered = _in_bundle_order(Path("subroutines", name) for name in names)
        assert [p.name for p in ordered] == [
            "alpha.csv",
            "b.csv",
            "Beta.csv",
            "Pump.csv",
            "pump.csv",
            "Zeta.CSV",
        ]

    def test_the_name_drops_the_last_four_characters(self) -> None:
        paths = [Path("subroutines", name) for name in ("..csv", "...csv", "Fan.CSV")]
        assert _subroutine_names(paths) == [".", "..", "Fan"]


class TestWriteRefusals:
    """Each refusal raises before ``write_bundle`` writes any file."""

    @pytest.fixture
    def bundle(self, tmp_path: Path) -> Path:
        """Return a directory that already holds a bundle and one other file.

        The bundle's rungs differ from the ones that the tests pass, so a write before a
        refusal would change the bytes.
        """
        root = tmp_path / "bundle"
        write_bundle(root, _project("Pump", "Fan", main=("X2", "Y3"), sub=("C2", "Y4")))
        (root / "notes.txt").write_text("kept", encoding="utf-8")
        return root

    @pytest.mark.parametrize(
        ("name", "match"),
        [
            ("a/b", "may not hold"),
            ("   ", "is blank"),
            ("x" * 25, "at most 24"),
            ("CON", "Windows device name"),
        ],
    )
    def test_a_bad_name(self, bundle: Path, name: str, match: str) -> None:
        before = _snapshot(bundle)
        with pytest.raises(FieldError, match=match) as info:
            write_bundle(bundle, _project("Pump", name))
        assert info.value.field == "Program.name"
        assert info.value.code in (Code.INVALID_SUBROUTINE_NAME, Code.BLANK_FIELD)
        assert _snapshot(bundle) == before

    @pytest.mark.parametrize("second", [" pump", "Pump"])
    def test_names_equal_ignoring_case(self, bundle: Path, second: str) -> None:
        """A name that differs only in case and the same name twice are refused alike.  A copy
        of the error and an unpickled copy have the same code and id."""
        before = _snapshot(bundle)
        with pytest.raises(WriterError) as info:
            write_bundle(bundle, _project("Pump", "Fan", second))
        error = info.value
        assert str(error) == (
            f"Subroutines 'Pump' and {second.strip()!r} have the same name when case is "
            "ignored (GUI-036). Rename one of them."
        )
        assert error.code is Code.DUPLICATE_SUBROUTINE_NAME
        assert error.click_id == "GUI-036"
        assert error.click_id in CLICK_IDS[error.code]
        assert _snapshot(bundle) == before
        for clone in (copy.copy(error), pickle.loads(pickle.dumps(error))):
            assert (str(clone), clone.code, clone.click_id) == (
                str(error),
                Code.DUPLICATE_SUBROUTINE_NAME,
                "GUI-036",
            )

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("a\x01b", "0001"),
            ("a\tb", "0009"),
            ("Fan\x7f", "007F"),
            ("\x1fPump", "001F"),
            ("Valve\n", "000A"),
        ],
    )
    def test_a_control_character(self, bundle: Path, name: str, code: str) -> None:
        before = _snapshot(bundle)
        with pytest.raises(WriterError) as info:
            write_bundle(bundle, _project("Pump", name))
        assert str(info.value) == (
            f"Subroutine {name!r} holds the control character U+{code}. Remove the "
            "character from the name."
        )
        assert info.value.code is None
        assert info.value.click_id is None
        assert _snapshot(bundle) == before

    def test_a_rung_that_the_csv_cannot_hold(self, bundle: Path) -> None:
        """The failing rung is in the last subroutine.  The error names that subroutine,
        and main and the other subroutine are not written."""
        project = _project("Pump", "Fan")
        project.subroutines[1].rungs.append(_unwritable_rung())
        before = _snapshot(bundle)
        with pytest.raises(WriterError, match=r"^Subroutine 'Fan': .* is 3 rows tall") as info:
            write_bundle(bundle, project)
        assert info.value.code is None
        assert info.value.click_id is None
        assert _snapshot(bundle) == before

    @pytest.mark.parametrize(
        ("target", "kind"),
        [("main.csv", "a file"), ("subroutines/Valve.csv", "a file"), ("subroutines", None)],
    )
    def test_a_path_of_the_wrong_kind(self, bundle: Path, target: str, kind: str | None) -> None:
        """A directory where ``write_bundle`` would write a file, or a file where it needs
        ``subroutines/``, is refused before any file is written."""
        path = bundle / target
        if kind is None:
            shutil.rmtree(path)
            path.write_text("kept", encoding="utf-8")
            kind = "a directory"
        else:
            if path.exists():
                path.unlink()
            path.mkdir()
        before = _snapshot(bundle)
        with pytest.raises(WriterError) as info:
            write_bundle(bundle, _project("Pump", "Valve"))
        assert str(info.value) == (
            f"{path} exists and is not {kind}. Move it or remove it, then write the bundle again."
        )
        assert info.value.code is None
        assert info.value.click_id is None
        assert _snapshot(bundle) == before

    def test_a_directory_that_is_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "bundle"
        path.write_text("kept", encoding="utf-8")
        with pytest.raises(WriterError, match="exists and is not a directory"):
            write_bundle(path, _project("Pump"))
        assert path.read_text(encoding="utf-8") == "kept"

    def test_a_rung_in_main(self, tmp_path: Path) -> None:
        """The error names the main program, and the missing directory is not created."""
        project = _project("Pump")
        project.main.rungs.append(_unwritable_rung())
        with pytest.raises(WriterError, match=r"^Main program: .* is 3 rows tall"):
            write_bundle(tmp_path / "bundle", project)
        assert not (tmp_path / "bundle").exists()


class TestOtherFiles:
    def test_a_stale_subroutine_file_is_left_and_read(self, tmp_path: Path) -> None:
        stale = _write_file(tmp_path / "subroutines" / "Old.csv", "return()")
        other = tmp_path / "rung_sources.json"
        other.write_text("{}", encoding="utf-8")
        before = stale.read_bytes()

        write_bundle(tmp_path, _project("Pump"))

        assert stale.read_bytes() == before
        assert other.read_text(encoding="utf-8") == "{}"
        back = read_bundle(tmp_path)
        assert [(sub.name, sub.prog_idx) for sub in back.subroutines] == [
            ("Old", 2),
            ("Pump", 3),
        ]

    def test_a_file_of_the_same_name_is_replaced(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "subroutines" / "Pump.csv", "return()", "return()")
        write_bundle(tmp_path, _project("Pump"))
        assert read_bundle(tmp_path) == _project("Pump")


class TestReadErrors:
    def test_missing_main(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "subroutines" / "Pump.csv", "return()")
        with pytest.raises(CsvError, match="missing required main.csv") as info:
            read_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(file=tmp_path / "main.csv")

    def test_a_refusal_in_a_subroutine_names_its_file(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "main.csv", "out(Y001)")
        _write_file(tmp_path / "subroutines" / "Alpha.csv", "out(Y002)")
        sub = _write_file(tmp_path / "subroutines" / "Beta.csv", "out(Y002)", "out(C9999)")
        with pytest.raises(AddressError, match="C9999") as info:
            read_bundle(tmp_path)
        location = CsvLocation.of(info.value)
        assert location is not None
        assert (location.file, location.line, location.column_name) == (sub, 3, "AF")
        assert str(info.value).endswith(f"(at {location})")

    def test_a_row_that_cannot_be_read_names_its_file(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "main.csv", "out(Y001)")
        sub = _write_file(tmp_path / "subroutines" / "Beta.csv", "out(Y002)", "nonsense(")
        with pytest.raises(CsvError) as info:
            read_bundle(tmp_path)
        location = CsvLocation.of(info.value)
        assert location is not None
        assert location.file == sub

    def test_a_file_name_that_click_refuses(self, tmp_path: Path) -> None:
        """Every file is one that can't be read, so a read before the check would raise a
        different error."""
        _unreadable(tmp_path / "main.csv")
        bad = _unreadable(tmp_path / "subroutines" / f"{'x' * 25}.csv")
        with pytest.raises(CsvError) as info:
            read_bundle(tmp_path)
        exc = info.value
        assert type(exc) is CsvError
        assert str(exc) == (
            f"The file name {bad.name!r} is not a subroutine name that CLICK accepts. "
            f"Program.name: {'x' * 25!r} is 25 characters; a subroutine name is at most 24. "
            f"Rename the file. (at {bad})"
        )
        assert CsvLocation.of(exc) == CsvLocation(file=bad)
        assert (exc.field, exc.code) == ("Program.name", Code.INVALID_SUBROUTINE_NAME)
        assert isinstance(exc.__cause__, FieldError)

    def test_a_file_named_only_csv(self, tmp_path: Path) -> None:
        """``.csv`` holds a blank name, which CLICK refuses.  No file can be read."""
        _unreadable(tmp_path / "main.csv")
        bad = _unreadable(tmp_path / "subroutines" / ".csv")
        with pytest.raises(CsvError, match="is blank") as info:
            read_bundle(tmp_path)
        assert info.value.code == Code.BLANK_FIELD
        assert CsvLocation.of(info.value) == CsvLocation(file=bad)

    @pytest.mark.parametrize("file_name", [" Pump.csv", "Pump\u00a0.csv", "\u3000Pump.csv"])
    def test_a_name_with_whitespace_at_one_end(self, tmp_path: Path, file_name: str) -> None:
        """``write_bundle`` strips the name, so this file could not come from a write.  An
        ASCII space, a no-break space and an ideographic space are each refused.  No file
        can be read."""
        _unreadable(tmp_path / "main.csv")
        _unreadable(tmp_path / "subroutines" / "Fan.csv")
        bad = _unreadable(tmp_path / "subroutines" / file_name)
        with pytest.raises(CsvError) as info:
            read_bundle(tmp_path)
        assert str(info.value) == (
            f"The subroutine name in {file_name!r} starts or ends with whitespace. Remove the "
            f"whitespace from the start and end of the file name. (at {bad})"
        )
        assert CsvLocation.of(info.value) == CsvLocation(file=bad)

    def test_names_equal_ignoring_case(self) -> None:
        """The paths are in memory, so the check reads no file."""
        sub = Path("subroutines")
        paths = [sub / "Fan.csv", sub / "Pump.csv", sub / "pump.CSV"]
        with pytest.raises(CsvError) as info:
            _subroutine_names(paths)
        assert str(info.value) == (
            "Subroutine files 'Pump.csv' and 'pump.CSV' have the same name when case is "
            f"ignored (GUI-036). Rename one of them. (at {sub / 'pump.CSV'})"
        )
        _assert_duplicate_name(info.value)

    def test_names_equal_ignoring_case_from_read_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``read_bundle`` is given the two paths in memory, so the test runs on a file
        system that ignores case.  None of the files exists, so a read would raise a
        different error."""
        sub = tmp_path / "subroutines"
        paths = (tmp_path / "main.csv", [sub / "Pump.csv", sub / "pump.csv"])
        monkeypatch.setattr(laddercodec.csv.bundle, "_bundle_paths", lambda _: paths)
        with pytest.raises(CsvError) as info:
            read_bundle(tmp_path)
        _assert_duplicate_name(info.value)
        assert CsvLocation.of(info.value) == CsvLocation(file=sub / "pump.csv")

    def test_names_equal_ignoring_case_on_disk(self, tmp_path: Path) -> None:
        """``read_bundle`` refuses the pair before it reads any file.  Every file is one that
        can't be read, so a read would raise a different error."""
        for name in ("main.csv", "subroutines/Pump.csv", "subroutines/pump.csv"):
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xff")
        if len(list((tmp_path / "subroutines").iterdir())) != 2:
            pytest.skip("this file system ignores case in file names")
        with pytest.raises(CsvError, match="have the same name when case is ignored") as info:
            read_bundle(tmp_path)
        _assert_duplicate_name(info.value)


def _assert_duplicate_name(error: CsvError) -> None:
    """Assert that *error* is the refusal of two subroutine files whose names are equal when
    case is ignored."""
    assert error.code is Code.DUPLICATE_SUBROUTINE_NAME
    assert error.click_id == "GUI-036"
    assert error.click_id in CLICK_IDS[error.code]
    assert error.field is None
    assert error.errors == (error,)


class TestReadOptions:
    """``strict`` and ``unchecked`` reach every file of the bundle."""

    @pytest.fixture
    def bundle(self, tmp_path: Path) -> Path:
        _write_file(tmp_path / "main.csv", "drum(DS1,DS2)", BAD_TIMER)
        _write_file(tmp_path / "subroutines" / "Pump.csv", "drum(DS1,DS2)", BAD_TIMER)
        return tmp_path

    def test_strict(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "main.csv", "out(Y001)")
        sub = _write_file(tmp_path / "subroutines" / "Pump.csv", "drum(DS1,DS2)")
        with pytest.raises(CsvError, match="Could not read 'drum") as info:
            read_bundle(tmp_path)
        assert CsvLocation.of(info.value).file == sub  # type: ignore[union-attr]

        _write_file(tmp_path / "main.csv", "drum(DS1,DS2)")
        back = read_bundle(tmp_path, strict=False)
        for program in (back.main, *back.subroutines):
            assert [rung.instructions[0] for rung in program.rungs] == [""]

    def test_unchecked(self, bundle: Path) -> None:
        with pytest.raises(FieldError):
            read_bundle(bundle, strict=False)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            back = read_bundle(bundle, strict=False, unchecked=True)
        found = [w for w in caught if issubclass(w.category, RefusedFieldWarning)]
        assert [w.message.program for w in found] == ["Main Program", "Pump"]  # type: ignore[union-attr]
        files = [CsvLocation.of(w.message.error).file for w in found]  # type: ignore[union-attr]
        assert files == [bundle / "main.csv", bundle / "subroutines" / "Pump.csv"]
        assert all(Path(w.filename) == Path(__file__) for w in found)
        for program in (back.main, *back.subroutines):
            assert program.rungs[1].instructions[0].to_csv() == BAD_TIMER
