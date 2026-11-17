"""Parse a file or a row in laddercodec's canonical CSV form of CLICK ladder logic."""

from __future__ import annotations

import csv
from collections.abc import Generator, Iterable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Literal

from ..errors import CsvError
from .ast import CanonicalRow, ParsedCsvFileAst, RowAst, RungAst
from .contract import (
    TOTAL_COLUMNS,
    is_rung_marker,
    is_valid_marker,
    validate_header,
)
from .location import AF_COLUMN, add_location, at, located, located_in_file
from .token_parser import parse_af_token, parse_condition_token


def _detect_file_role(path: Path) -> tuple[Literal["main", "subroutine"], str | None]:
    if path.name == "main.csv":
        return "main", None
    # A CSV file in a folder named "subroutines" is a subroutine, and its stem is the slug.
    if path.parent.name == "subroutines" and path.suffix.lower() == ".csv":
        return "subroutine", path.stem
    return "subroutine", None


def _canonical_row_from_fields(fields: list[str]) -> CanonicalRow:
    marker = fields[0].strip() if fields else ""
    if not is_valid_marker(marker):
        raise CsvError(
            f"Invalid marker {marker!r}; expected 'R' (optionally indexed, e.g. R1), '#', or blank"
        )

    # A comment row may hold only the marker and the text, so pad it to the full width.
    # Keep the spaces in column A, because a comment may be indented like code.
    if marker == "#":
        padded = fields + [""] * (TOTAL_COLUMNS - len(fields))
        text = padded[1] if len(padded) > 1 else ""
        rest = tuple(cell.strip() for cell in padded[2:-1])
        conditions = (text,) + rest
        # conditions[i] is column i. Column A holds the text, and every later column must
        # be blank. In a row longer than the header, conditions[31] is the AF cell.
        column = next((i for i, cell in enumerate(conditions) if i and cell), None)
        if column is not None:
            raise at(
                CsvError("Comment rows may only populate column A text"),
                column=column if column <= AF_COLUMN else None,
            )
        return CanonicalRow(marker=marker, conditions=conditions, af="")

    if len(fields) != TOTAL_COLUMNS:
        raise CsvError(f"Expected {TOTAL_COLUMNS} columns; got {len(fields)}")

    conditions = tuple(cell.strip() for cell in fields[1:-1])
    af = fields[-1].strip()

    return CanonicalRow(marker=marker, conditions=conditions, af=af)


def _row_ast(canonical: CanonicalRow, line: int | None = None) -> RowAst:
    condition_nodes = []
    try:
        for token in canonical.conditions:
            condition_nodes.append(parse_condition_token(token))
    except Exception as exc:
        add_location(exc, column=len(condition_nodes))  # the cell that failed
        raise
    try:
        af_node = parse_af_token(canonical.af)
    except Exception as exc:
        add_location(exc, column=AF_COLUMN)
        raise
    return RowAst(
        canonical=canonical, condition_nodes=tuple(condition_nodes), af_node=af_node, line=line
    )


def _rows_ast(records: Iterable[tuple[int | None, Sequence[str]]]) -> tuple[RowAst, ...]:
    """Parse each (line, fields) record into a ``RowAst``.

    The location of an error names the record's line. For a row in a rung, it also names
    the line of the rung's ``R`` row and the row's index in the rung. These are the rungs
    that ``_segment_rungs`` forms.
    """
    places: list[dict[str, int | None]] = []
    canonical_rows: list[CanonicalRow] = []
    rung_line: int | None = None
    row: int | None = None
    for line, fields in records:
        marker = fields[0].strip() if fields else ""
        if is_rung_marker(marker):
            rung_line, row = line, 0
        elif marker == "#":  # a comment row ends the rung above it
            rung_line = row = None
        elif row is not None:  # a continuation row, or a row whose bad marker is refused below
            row += 1
        place = {"line": line, "rung_line": rung_line, "row": row}
        places.append(place)
        try:
            canonical_rows.append(_canonical_row_from_fields(list(fields)))
        except Exception as exc:
            add_location(exc, **place)
            raise
    # Every row's shape is checked before any row's tokens.
    rows: list[RowAst] = []
    for canonical, place in zip(canonical_rows, places, strict=True):
        try:
            rows.append(_row_ast(canonical, place["line"]))
        except Exception as exc:
            add_location(exc, **place)
            raise
    return tuple(rows)


def _segment_rungs(rows: tuple[RowAst, ...]) -> tuple[RungAst, ...]:
    rungs: list[RungAst] = []
    current: list[RowAst] = []
    current_comments: list[RowAst] = []
    pending_comments: list[RowAst] = []

    for row in rows:
        if row.canonical.is_comment:
            if current:
                rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))
                current = []
                current_comments = []
            pending_comments.append(row)
            continue

        if is_rung_marker(row.canonical.marker):
            if current:
                rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))
            current = [row]
            current_comments = pending_comments
            pending_comments = []
            continue

        if not current:
            raise at(
                CsvError("Continuation row encountered before first 'R' marker"), line=row.line
            )

        current.append(row)

    if pending_comments:
        raise at(
            CsvError("Comment row encountered without following 'R' marker"),
            line=pending_comments[0].line,
        )

    if current:
        rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))

    return tuple(rungs)


def _parse_single_rung_rows(row_fields: Sequence[Sequence[str]]) -> RungAst:
    """Parse in-memory canonical row fields into exactly one ``RungAst``."""
    rows = _rows_ast((None, fields) for fields in row_fields)
    rungs = _segment_rungs(rows)
    if not rungs:
        raise CsvError("Expected one rung in emitted CSV rows; got none")
    if len(rungs) != 1:
        raise CsvError(f"Expected one rung in emitted CSV rows; got {len(rungs)}")
    return rungs[0]


def _read_records(path: Path) -> Generator[tuple[int | None, Sequence[str]]]:
    """Yield each row after the header with the line that the row starts on.

    Read the file one row at a time, as the caller asks for rows.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header: list[str] | None = None
        end = 0  # the last line read
        try:
            for parsed in reader:
                start, end = end + 1, reader.line_num
                if not parsed:
                    continue
                if header is None:
                    header = [cell.strip() for cell in parsed]
                    with located(line=start):
                        validate_header(header)
                    continue
                yield start, parsed
        except csv.Error as exc:
            # The location is the line that the row being read starts on.
            raise at(CsvError(str(exc)), line=end + 1) from exc
        except UnicodeDecodeError as exc:
            # The file is decoded in blocks, so the line is not known. The location names
            # only the file.
            raise CsvError(str(exc)) from exc

    if header is None:
        raise CsvError("CSV file is empty; expected header row")


def parse_row(row: str) -> CanonicalRow:
    """Parse a single canonical CSV row string into a ``CanonicalRow``."""
    fields = next(csv.reader([row]), [])
    return _canonical_row_from_fields(fields)


def parse_csv_file(
    path: Path | str,
    syntax: Literal["canonical"] = "canonical",
) -> ParsedCsvFileAst:
    """Parse a canonical CSV file into rows and rungs.

    Every exception raised for a bad CSV carries a ``CsvLocation`` as its ``location``
    (``laddercodec.CsvLocation``), and its message ends with that location.
    """
    path_obj = Path(path)
    with located_in_file(path_obj):
        # Closing the reader closes the file before an error leaves this block.
        with closing(_read_records(path_obj)) as records:
            rows = _rows_ast(records)
        rungs = _segment_rungs(rows)
    role, subroutine_slug = _detect_file_role(path_obj)
    return ParsedCsvFileAst(
        path=path_obj,
        role=role,
        subroutine_slug=subroutine_slug,
        rows=rows,
        rungs=rungs,
    )
