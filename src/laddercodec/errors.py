"""The errors laddercodec raises: one tree under :class:`LaddercodecError`.

``decode()``, ``decode_program()``, ``encode()``, ``read_csv()``, ``write_csv()`` and
``check()`` raise a ``LaddercodecError`` for input they can't read or write.  Each class
is a ``ValueError``, so ``except ValueError`` catches every one of them.
``FieldError`` and ``AddressError`` (:mod:`laddercodec.operands.errors`) join the tree
under :class:`LaddercodecError` too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .operands.errors import FieldError, Reason


class LaddercodecError(ValueError):
    """The base of the errors laddercodec raises for input it can't read or write.

    ``except LaddercodecError`` catches all of them, and so does ``except ValueError``.
    """


class DecodeError(LaddercodecError):
    """Raised when a clipboard binary or a program file cannot be decoded.

    ``decode()`` raises it for a bad envelope (magic or size), and ``decode_program()``
    for a file header it can't read.
    """


class EncodeError(LaddercodecError):
    """Raised when ``encode()`` is given a rung it can't write.

    For example: a grid of the wrong size, a wire token where CLICK can't draw one,
    more than one ``NOP``, an undecoded marker, or a comment too long once written as
    RTF.  A value CLICK's dialog refuses raises :class:`~laddercodec.FieldError` instead.
    """


class CsvError(LaddercodecError):
    """Raised when ``read_csv`` cannot read a CSV: a file that isn't UTF-8 text, or a row,
    a token or a rung it can't read.

    Like every error ``read_csv`` raises for a bad CSV, it carries a
    :class:`~laddercodec.CsvLocation` as its ``location``.

    A ``FieldError`` refused while a box takes its pin rows is still wrapped: it arrives as
    a ``CsvError`` (not a ``FieldError``, so ``except FieldError`` does not catch it),
    now carrying the refusal's data.  ``field``, ``fields``, ``reason`` and ``click_id``
    are those of the first refusal, as ``FieldError`` has them, and ``errors`` holds every
    refusal of the box, each a ``FieldError`` with its own ``location``; ``errors[0]`` is the
    wrapped ``FieldError`` (also ``__cause__``), not this exception.  A refusal a pin row's
    value causes is located at that pin's row, any other at the box's own row.  An error that is
    no field refusal (a pin token that does not parse, a rung with no rows) has ``field``,
    ``reason`` and ``click_id`` ``None``, empty ``fields``, and ``errors == (self,)``.
    """

    field: str | None
    fields: tuple[str, ...]
    reason: Reason | None
    click_id: str | None
    errors: tuple[FieldError, ...] | tuple[CsvError]

    def __init__(
        self,
        *args: object,
        field: str | None = None,
        refusal: FieldError | None = None,
    ) -> None:
        super().__init__(*args)
        if refusal is None:
            self.field = field
            self.fields = () if field is None else (field,)
            self.reason = None
            self.click_id = None
            self.errors = (self,)
        else:
            self.field = refusal.field
            self.fields = refusal.fields
            self.reason = refusal.reason
            self.click_id = refusal.click_id
            self.errors = refusal.errors


class WriterError(LaddercodecError):
    """Raised by ``write_csv`` for a rung the CSV can't hold, or for a bad ``stop=``.

    A bad ``stop=`` is neither ``"end"`` nor ``"return"``; it is refused before anything is
    written.
    """


class LayoutError(LaddercodecError):
    """A rung CLICK's syntax check refuses, or one this layout cannot draw.

    ``code`` is CLICK's error code when CLICK is known to refuse the shape (``C0001``: not
    series-parallel; ``C0202``: a contact no rail reaches), else ``None``.
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
