"""CSV row/file parser for Click Ladder canonical CSV rows."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Literal

from .ast import CanonicalRow, ParsedCsvFileAst, RowAst, RungAst
from .contract import (
    CONDITION_COLUMNS,
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
    # subroutines/ folder layout: parent dir is "subroutines", slug is stem
    if path.parent.name == "subroutines" and path.suffix.lower() == ".csv":
        return "subroutine", path.stem
    return "subroutine", None


def _canonical_row_from_fields(fields: list[str]) -> CanonicalRow:
    marker = fields[0].strip() if fields else ""
    if not is_valid_marker(marker):
        raise ValueError(
            f"Invalid marker {marker!r}; expected 'R' (optionally indexed, e.g. R1), '#', or blank"
        )

    # Comment rows may be short (just marker + text); pad to full width.
    # Preserve whitespace in column A for code-style comments (indentation).
    if marker == "#":
        padded = fields + [""] * (TOTAL_COLUMNS - len(fields))
        text = padded[1] if len(padded) > 1 else ""
        rest = tuple(cell.strip() for cell in padded[2:-1])
        conditions = (text,) + rest
        # conditions[i] is column i: A holds the text, B onwards must be blank.
        column = next((i for i, cell in enumerate(conditions) if i and cell), None)
        if column is not None:
            raise at(
                ValueError("Comment rows may only populate column A text"),
                column=column if column < len(CONDITION_COLUMNS) else None,
            )
        return CanonicalRow(marker=marker, conditions=conditions, af="")

    if len(fields) != TOTAL_COLUMNS:
        raise ValueError(f"Expected {TOTAL_COLUMNS} columns; got {len(fields)}")

    conditions = tuple(cell.strip() for cell in fields[1:-1])
    af = fields[-1].strip()

    return CanonicalRow(marker=marker, conditions=conditions, af=af)


def _row_ast(canonical: CanonicalRow, line: int | None = None) -> RowAst:
    condition_nodes = []
    for column, token in enumerate(canonical.conditions):
        with located(column=column):
            condition_nodes.append(parse_condition_token(token))
    with located(column=AF_COLUMN):
        af_node = parse_af_token(canonical.af)
    return RowAst(
        canonical=canonical, condition_nodes=tuple(condition_nodes), af_node=af_node, line=line
    )


def _rows_ast(records: Iterable[tuple[int | None, Sequence[str]]]) -> tuple[RowAst, ...]:
    """Parse each (line, fields) record into a ``RowAst``.

    An error names the record's line and, for a row under an ``R`` row, the line of that
    ``R`` row and the row's index in its rung (the rungs ``_segment_rungs`` forms).
    """
    places: list[dict[str, int | None]] = []
    canonical_rows: list[CanonicalRow] = []
    rung_line: int | None = None
    row: int | None = None
    for line, fields in records:
        marker = fields[0].strip() if fields else ""
        if is_rung_marker(marker):
            rung_line, row = line, 0
        elif marker == "" and row is not None:
            row += 1
        else:  # a comment row ends the rung above it; an invalid marker is refused below
            rung_line = row = None
        places.append({"line": line, "rung_line": rung_line, "row": row})
        with located(**places[-1]):
            canonical_rows.append(_canonical_row_from_fields(list(fields)))
    # Every row's shape is checked before any row's tokens.
    rows: list[RowAst] = []
    for canonical, place in zip(canonical_rows, places, strict=True):
        with located(**place):
            rows.append(_row_ast(canonical, place["line"]))
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
                ValueError("Continuation row encountered before first 'R' marker"), line=row.line
            )

        current.append(row)

    if pending_comments:
        raise at(
            ValueError("Comment row encountered without following 'R' marker"),
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
        raise ValueError("Expected one rung in emitted CSV rows; got none")
    if len(rungs) != 1:
        raise ValueError(f"Expected one rung in emitted CSV rows; got {len(rungs)}")
    return rungs[0]


def _read_records(path: Path) -> Iterator[tuple[int | None, Sequence[str]]]:
    """The rows after the header, each with the line it starts on, read as they are taken."""
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
            add_location(exc, line=reader.line_num)
            raise

    if header is None:
        raise ValueError(f"CSV file {path} is empty; expected header row")


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
        rows = _rows_ast(_read_records(path_obj))
        rungs = _segment_rungs(rows)
    role, subroutine_slug = _detect_file_role(path_obj)
    return ParsedCsvFileAst(
        path=path_obj,
        role=role,
        subroutine_slug=subroutine_slug,
        rows=rows,
        rungs=rungs,
    )
