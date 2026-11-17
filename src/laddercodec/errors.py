"""The exceptions that laddercodec raises. Each one is a subclass of :class:`LaddercodecError`.

``decode()``, ``decode_program()``, ``encode()``, ``read_csv()``, ``write_csv()`` and
``check()`` raise a ``LaddercodecError`` for input they can't read or write.  Each class
is a ``ValueError``, so ``except ValueError`` catches every one of them.
``FieldError`` and ``AddressError`` are defined in :mod:`laddercodec.operands.errors`, and
they are subclasses of :class:`LaddercodecError` too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .codes import Code

if TYPE_CHECKING:
    from .operands.errors import FieldError, Reason


class LaddercodecError(ValueError):
    """The base class of every error that laddercodec raises for input it can't read or write.

    ``except LaddercodecError`` catches all of them, and so does ``except ValueError``.
    """


class DecodeError(LaddercodecError):
    """Raised when a clipboard binary or a program file cannot be decoded.

    For example, ``decode()`` raises it when the binary does not start with the expected
    magic bytes or is too short.  ``decode_program()`` raises it when it can't read
    the file header.
    """


class EncodeError(LaddercodecError):
    """Raised when ``encode()`` is given a rung it can't write.

    Examples are a grid of the wrong size, a vertical wire token in a cell where CLICK
    can't draw one, more than one ``NOP``, an undecoded marker, and a comment that is too
    long once it is written as RTF.  A value that CLICK's dialog refuses raises
    :class:`~laddercodec.FieldError` instead.
    """


class CsvError(LaddercodecError):
    """Raised when ``read_csv`` cannot read a CSV.

    ``read_csv`` raises it for a file that isn't UTF-8 text, and for a row, a token or a
    rung that it can't read.  Like every error that ``read_csv`` raises for a bad CSV, it
    has a :class:`~laddercodec.CsvLocation` as its ``location`` attribute.

    Some boxes, such as a counter, take inputs from pin rows below the box's own row.
    ``read_csv`` builds such a box from all of its rows.  If the box refuses a value at that
    step, the ``FieldError`` reaches you wrapped in a ``CsvError``, and ``except FieldError``
    does not catch it.  The ``CsvError`` copies the refusal's data.  ``field``, ``fields``,
    ``reason``, ``code`` and ``click_id`` are those of the first refusal, with the meanings
    they have on ``FieldError``.  ``errors`` holds every refusal for the box, and each is a
    ``FieldError`` with its own ``location``.  ``errors[0]`` is the wrapped ``FieldError``,
    which is also ``__cause__``.  It is not this exception.  A refusal of a value that a pin
    row sets is located at that pin's row.  Any other refusal is located at the box's own row.

    A ``CsvError`` that is not about a refused field has ``field``, ``reason``, ``code`` and
    ``click_id`` set to ``None``, an empty ``fields``, and ``errors == (self,)``.  A pin
    token that does not parse and a rung with no rows are two examples.
    """

    field: str | None
    fields: tuple[str, ...]
    reason: Reason | None
    code: Code | None
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
            self.code = None
            self.click_id = None
            self.errors = (self,)
        else:
            self.field = refusal.field
            self.fields = refusal.fields
            self.reason = refusal.reason
            self.code = refusal.code
            self.click_id = refusal.click_id
            self.errors = refusal.errors


class WriterError(LaddercodecError):
    """Raised when ``write_csv`` is given a rung it can't write as CSV, or a bad ``stop=``.

    ``stop=`` must be ``"end"`` or ``"return"``.  ``write_csv`` checks it before it writes
    anything.
    """


class LayoutError(LaddercodecError):
    """Raised when a rung has a shape that CLICK's syntax check refuses, or one that
    laddercodec's layout cannot draw.

    ``code`` names the shape.  It is a Code such as ``"not-series-parallel"``.  ``click_id``
    is CLICK's error id when CLICK is known to refuse the shape (``C0001``, ``C0202``).
    Otherwise it is ``None``.
    """

    def __init__(self, message: str, click_id: str | None = None, *, code: Code) -> None:
        super().__init__(message)
        self.code = code
        self.click_id = click_id

    def __reduce__(self) -> tuple[Any, ...]:
        # Unpickling calls the class with args alone. LayoutError requires code, so pass it too.
        return (
            _rebuild_layout,
            (type(self), self.args[0], self.click_id, self.code),
            self.__dict__,
        )


def _rebuild_layout(
    cls: type[LayoutError], message: str, click_id: str | None, code: Code
) -> LayoutError:
    """Rebuild a pickled :class:`LayoutError` from its message, CLICK id and code.

    Pickle then restores the error's other attributes from its saved ``__dict__``.
    """
    return cls(message, click_id=click_id, code=code)
