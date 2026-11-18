"""The exceptions that laddercodec raises. Each one is a subclass of :class:`LaddercodecError`.

``decode()``, ``decode_program()``, ``encode()``, ``read_csv()``, ``write_csv()``,
``csv_rows()``, ``read_bundle()``, ``write_bundle()`` and ``check()`` raise a
``LaddercodecError`` for input they can't read or write.  Each class is a ``ValueError``,
so ``except ValueError`` catches every one of them.
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
    """Raised when ``read_csv`` or ``read_bundle`` cannot read a CSV.

    ``read_csv`` raises it for a file that isn't UTF-8 text, and for a row, a token or a
    rung that it can't read.  Like every error that ``read_csv`` raises for a bad CSV, it
    has a :class:`~laddercodec.CsvLocation` as its ``location`` attribute.

    ``read_bundle`` raises it for the same reasons in any file of the bundle.  It also
    raises it when ``main.csv`` is missing, when CLICK refuses the name of a file in
    ``subroutines/`` as a subroutine name, when one of those names starts or ends with
    whitespace, and when two of them are equal with case ignored.  For a name that CLICK
    refuses, the ``CsvError`` copies the refusal's data in the same way as for a pin row,
    described next.

    Some boxes, such as a counter, take inputs from pin rows below the box's own row.
    ``read_csv`` builds such a box from all of its rows.  If the box refuses a value at that
    step, the ``FieldError`` reaches you wrapped in a ``CsvError``, and ``except FieldError``
    does not catch it.  The ``CsvError`` copies the refusal's data.  ``field``, ``fields``,
    ``reason``, ``code`` and ``click_id`` are those of the first refusal, with the meanings
    they have on ``FieldError``.  ``errors`` holds every refusal for the box, and each is a
    ``FieldError`` with its own ``location``.  ``errors[0]`` is the wrapped ``FieldError``,
    which is also ``__cause__``.  It is not this exception.  A refusal of a value that a pin
    row sets is located at that pin's row.  Any other refusal is located at the box's own row.

    A ``CsvError`` that is not about a refused field has ``field``, ``reason`` and
    ``click_id`` set to ``None``, an empty ``fields``, and ``errors == (self,)``.  Its
    ``code`` is ``None``, except for a rung of more than 32 rows, described next.  A pin
    token that does not parse and a rung with no rows are two examples.

    ``read_csv`` and ``read_bundle`` also raise it for a rung that needs more than the 32 rows
    of a CLICK rung, in strict and in relaxed mode.  Its ``code`` is then
    ``layout-too-tall``, and its location is the rung's ``R`` row.
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
        code: Code | None = None,
    ) -> None:
        super().__init__(*args)
        if refusal is None:
            self.field = field
            self.fields = () if field is None else (field,)
            self.reason = None
            self.code = code
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
    """Raised when ``write_csv`` or ``csv_rows`` is given a rung that the CSV can't hold, or
    a bad ``stop=``.

    ``stop=`` must be ``"end"`` or ``"return"``.  ``write_csv`` builds every row before it
    opens the file.  If it raises ``WriterError``, it has not created or changed the file.

    ``write_bundle`` raises it for a rung that the CSV can't hold, for two subroutines whose
    names are equal when case is ignored, for a subroutine name that holds a control
    character, and for a path that it would write that exists and is of the wrong kind.  It
    raises before it writes any file.

    ``write_csv``, ``csv_rows`` and ``write_bundle`` raise it for a rung that needs more than
    the 32 rows of a CLICK rung.  The ``__cause__`` is then a :class:`LayoutError` with the
    code ``layout-too-tall``.
    """


class LayoutError(LaddercodecError):
    """Raised by :func:`~laddercodec.lay_out` for a circuit that CLICK can't hold or that
    laddercodec can't draw.

    ``code`` is a :class:`~laddercodec.Code` that says why:

    - ``layout-too-tall``: a rung needs more than 32 rows.
    - ``layout-too-wide``: a rung needs more than the 31 condition columns.
    - ``layout-cannot-draw``: two wires or two cells of the drawing would fall on one place.
    - ``layout-nop-split``: outputs meet only at the rail, and one of them is a NOP.

    ``click_id`` is ``None`` for these codes.  When ``write_csv`` can't lay out a rung, it
    raises :class:`~laddercodec.WriterError`.  The ``__cause__`` of that error can be a
    ``LayoutError`` with one of these codes, or with the code of a ``check()`` finding such
    as ``not-series-parallel``.  Its ``click_id`` is then CLICK's id when CLICK has one, such
    as ``C0001``.
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
