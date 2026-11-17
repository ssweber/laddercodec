"""Bundle parser for Click Ladder CSV directory exports."""

from __future__ import annotations

from pathlib import Path

from ..errors import CsvError
from .ast import ProgramBundleAst
from .location import located_in_file
from .parser import parse_csv_file


def parse_bundle(directory: Path | str) -> ProgramBundleAst:
    """Parse ``main.csv`` and ``subroutines/*.csv`` of a bundle directory.

    An exception raised for a bad file carries a ``CsvLocation`` (``laddercodec.CsvLocation``)
    whose ``file`` is the file at fault: ``main.csv`` when it is missing.
    """
    dir_path = Path(directory)
    main_path = dir_path / "main.csv"
    if not main_path.exists():
        with located_in_file(main_path):
            raise CsvError(f"Bundle directory {dir_path} is missing required main.csv")

    main = parse_csv_file(main_path, syntax="canonical")

    sub_dir = dir_path / "subroutines"
    if sub_dir.is_dir():
        sub_paths = sorted(
            p for p in sub_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"
        )
    else:
        sub_paths = []
    subroutines = tuple(parse_csv_file(path, syntax="canonical") for path in sub_paths)
    return ProgramBundleAst(directory=dir_path, main=main, subroutines=subroutines)
