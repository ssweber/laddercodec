"""Read and write a CSV bundle: a directory with ``main.csv`` and a ``subroutines/`` folder."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from ..errors import CsvError, LaddercodecError, WriterError
from ..model import FieldError, Program, Project, check_program_name
from ..refused import warn_refused
from ..undecoded import UndecodedStop
from .ast import ProgramBundleAst
from .location import located_in_file
from .parser import csv_stem, parse_csv_file
from .reader import read_rungs
from .writer import _csv_rows, write_rows

#: The name that ``read_bundle`` gives the main program. CLICK names it the same.
MAIN_PROGRAM_NAME = "Main Program"

#: The field that a refused subroutine name is reported against.
_NAME_FIELD = "Program.name"


def _bundle_paths(directory: Path) -> tuple[Path, list[Path]]:
    """Return the path of ``main.csv`` in *directory* and the paths of its subroutine files.

    The subroutine files are the files directly in ``subroutines/`` whose names end in
    ``.csv``, in any case, in the order of :func:`_in_bundle_order`.  Raise ``CsvError``
    if ``main.csv`` is missing.
    """
    main_path = directory / "main.csv"
    if not main_path.exists():
        with located_in_file(main_path):
            raise CsvError(f"Bundle directory {directory} is missing required main.csv")
    sub_dir = directory / "subroutines"
    if not sub_dir.is_dir():
        return main_path, []
    return main_path, _in_bundle_order(
        p for p in sub_dir.iterdir() if p.is_file() and csv_stem(p) is not None
    )


def _in_bundle_order(paths: Iterable[Path]) -> list[Path]:
    """Return the subroutine files in *paths* sorted by stem, ignoring case first.

    Two stems that are equal when case is ignored are sorted by their exact text.  The
    order is the same on every operating system.
    """

    def key(path: Path) -> tuple[str, str]:
        stem = csv_stem(path) or ""
        return stem.casefold(), stem

    return sorted(paths, key=key)


def parse_bundle(directory: Path | str) -> ProgramBundleAst:
    """Parse ``main.csv`` and ``subroutines/*.csv`` of a bundle directory.

    An exception raised for a bad file has a ``CsvLocation`` (``laddercodec.CsvLocation``)
    whose ``file`` is the file at fault.  If ``main.csv`` is missing, ``file`` is the path
    where ``main.csv`` should be.
    """
    dir_path = Path(directory)
    main_path, sub_paths = _bundle_paths(dir_path)
    main = parse_csv_file(main_path, syntax="canonical")
    subroutines = tuple(parse_csv_file(path, syntax="canonical") for path in sub_paths)
    return ProgramBundleAst(directory=dir_path, main=main, subroutines=subroutines)


def read_bundle(directory: Path | str, *, strict: bool = True, unchecked: bool = False) -> Project:
    """Read the bundle in *directory* and return it as a ``Project``.

    A bundle is a directory that holds ``main.csv`` and, optionally, a ``subroutines/``
    folder with one ``<name>.csv`` file for each subroutine::

        project = read_bundle("my_program")
        project.main.rungs              # list[Rung], from main.csv
        project.subroutines[0].name     # the first file's name, without .csv

    The main program comes back as ``"Main Program"``, the name CLICK gives it, with
    ``prog_idx`` 1.  The subroutines are the files directly in ``subroutines/`` whose
    names end in ``.csv``, in any case.  Each subroutine is named after its file's
    name without the last four characters, ``.csv``.  ``read_bundle`` sorts the
    subroutines by name, ignoring case, and the order is the same on every operating
    system.  Their ``prog_idx`` values are 2, 3, 4 and so on, in that order.
    ``read_bundle`` ignores every other file.

    ``read_bundle`` reads each file as :func:`~laddercodec.read_csv` reads it, with the
    same *strict* and *unchecked*.  When *unchecked* is ``True``, each
    ``RefusedFieldWarning`` names its program.

    Raises
    ------
    CsvError
        If ``main.csv`` is missing, if a file can't be read, or if the names of the
        files in ``subroutines/`` are refused.  ``read_bundle`` checks the names before
        it reads any file.  It refuses a name that CLICK refuses as a subroutine name, a
        name that starts or ends with whitespace, and two names that are equal when case
        is ignored.  For a name that CLICK refuses, the ``CsvError`` copies the
        ``FieldError``'s ``field``, ``code``, ``reason`` and ``click_id``.
    FieldError
        If a file holds a value that CLICK's dialog refuses, as ``read_csv`` raises it.
        It is an ``AddressError`` for an address.

    Each error has a :class:`~laddercodec.CsvLocation` as its ``location``.  The
    location's ``file`` is the file at fault.  If ``main.csv`` is missing, ``file`` is
    the path where ``main.csv`` should be.
    """
    main_path, sub_paths = _bundle_paths(Path(directory))
    names = _subroutine_names(sub_paths)
    main = Program(MAIN_PROGRAM_NAME, 1, read_rungs(main_path, strict=strict, unchecked=unchecked))
    subroutines = [
        Program(name, prog_idx, read_rungs(path, strict=strict, unchecked=unchecked))
        for prog_idx, (name, path) in enumerate(zip(names, sub_paths, strict=True), start=2)
    ]
    if unchecked:
        for program in (main, *subroutines):
            warn_refused(program.rungs, program=program.name)
    return Project(main=main, subroutines=subroutines)


def _subroutine_names(paths: Sequence[Path]) -> list[str]:
    """Return the subroutine name of each file in *paths*: its name without ``.csv``.

    Raise ``CsvError`` if CLICK refuses a name as a subroutine name, if a name starts or
    ends with whitespace, or if two names are equal when case is ignored.  Read no file.
    """
    names: list[str] = []
    seen: dict[str, Path] = {}
    for path in paths:
        name = csv_stem(path) or ""
        with located_in_file(path):
            try:
                check_program_name(name, _NAME_FIELD)
            except FieldError as exc:
                raise CsvError(
                    f"The file name {path.name!r} is not a subroutine name that CLICK "
                    f"accepts. {exc}. Rename the file.",
                    refusal=exc,
                ) from exc
            if name != name.strip():
                # write_bundle strips the name, so this file could not come back from a
                # write.
                raise CsvError(
                    f"The subroutine name in {path.name!r} starts or ends with whitespace. "
                    "Remove the whitespace from the start and end of the file name."
                )
            first = seen.setdefault(name.casefold(), path)
            if first is not path:
                raise CsvError(
                    f"Subroutine files {first.name!r} and {path.name!r} have the same name "
                    "when case is ignored. Rename one of them."
                )
        names.append(name)
    return names


def write_bundle(directory: Path | str, project: Project, *, index: bool = False) -> None:
    """Write *project* to *directory* as a bundle that :func:`read_bundle` reads.

    ``write_bundle`` writes these files and creates the directories that are missing::

        <directory>/
          main.csv              the main program
          subroutines/
            <name>.csv          one file for each subroutine

    ``<name>`` is the subroutine's ``Program.name`` with the whitespace stripped from
    both ends.  ``write_bundle`` does not write ``project.main.name``.  ``read_bundle``
    names the main program ``"Main Program"``.  ``write_bundle`` creates
    ``subroutines/`` even when the project has no subroutines.  It replaces a file that
    has the same name.  It does not delete or change any other file in *directory*.  A
    file in ``subroutines/`` from an earlier write stays there when *project* has no
    subroutine of that name, and ``read_bundle`` reads it.

    Each file holds what :func:`~laddercodec.write_csv` writes for the program's rungs.
    ``main.csv`` is written with ``stop="end"`` and each subroutine with
    ``stop="return"``.  With ``index=True``, each file numbers its rungs from ``R1``.

    ``write_bundle`` does not write ``prog_idx``, and the files have no order.  When you
    read the bundle back, ``read_bundle`` returns the subroutines sorted by name,
    ignoring case, with ``prog_idx`` 2, 3, 4 and so on.

    Raises
    ------
    FieldError
        If CLICK refuses a subroutine's name.  The ``field`` is ``Program.name``.
    WriterError
        If two subroutines have names that are equal when case is ignored.  They would be
        one file on Windows and macOS.  It is also raised for a name that holds a control
        character, U+0000 to U+001F or U+007F, anywhere in the name.  It is raised when
        *directory*, ``subroutines/``, ``main.csv`` or a subroutine's file exists and is
        of the wrong kind, such as a directory named ``main.csv``.  ``write_bundle``
        also raises it for a rung that the CSV can't hold, as ``write_csv`` does.

    ``write_bundle`` checks the names and the paths, and builds the rows of every file,
    before it writes any file.  If it raises ``FieldError`` or ``WriterError``, it has
    not created or changed any file.  The message of an error from a program's rungs
    starts with the program: ``Main program:`` or ``Subroutine 'Pump':``.  An
    ``OSError`` while it writes, such as a full disk, can leave some files written and
    others not.
    """
    directory = Path(directory)
    names: dict[str, str] = {}
    for program in project.subroutines:
        check_program_name(program.name, _NAME_FIELD)
        # Check the name before it is stripped, so that a control character at either end,
        # which strip() would remove, is refused too.  A file name can't hold U+0000, and
        # Windows refuses U+0001 to U+001F.  U+007F is refused with them.
        control = next((ch for ch in program.name if ch < " " or ch == "\x7f"), None)
        if control is not None:
            raise WriterError(
                f"Subroutine {program.name!r} holds the control character "
                f"U+{ord(control):04X}. Remove the character from the name."
            )
        name = program.name.strip()
        key = name.casefold()
        if key in names:
            raise WriterError(
                f"Subroutines {names[key]!r} and {name!r} have the same name when case is "
                "ignored, so they would be one file in subroutines/. Rename one of them."
            )
        names[key] = name

    sub_dir = directory / "subroutines"
    programs: list[tuple[Path, Program, UndecodedStop, str]] = [
        (directory / "main.csv", project.main, "end", "Main program")
    ]
    for name, program in zip(names.values(), project.subroutines, strict=True):
        programs.append((sub_dir / f"{name}.csv", program, "return", f"Subroutine {name!r}"))

    for folder in (directory, sub_dir):
        if folder.exists() and not folder.is_dir():
            raise WriterError(
                f"{folder} exists and is not a directory. Move it or remove it, then write "
                "the bundle again."
            )
    for path, *_ in programs:
        if path.exists() and not path.is_file():
            raise WriterError(
                f"{path} exists and is not a file. Move it or remove it, then write the "
                "bundle again."
            )

    files: list[tuple[Path, list[list[str]]]] = []
    for path, program, stop, label in programs:
        try:
            # Called here, not in a helper, so that an UndecodedRungWarning names the line
            # that called write_bundle.
            rows = _csv_rows(program.rungs, index=index, stop=stop, caller="write_bundle")
        except LaddercodecError as exc:
            _start_message(exc, label)
            raise
        files.append((path, rows))

    sub_dir.mkdir(parents=True, exist_ok=True)
    for path, rows in files:
        write_rows(path, rows)


def _start_message(exc: BaseException, label: str) -> None:
    """Start the message of *exc* with ``<label>:`` if its only argument is its message."""
    if len(exc.args) == 1 and isinstance(exc.args[0], str):
        exc.args = (f"{label}: {exc.args[0]}",)
