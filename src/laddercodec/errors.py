"""The exceptions that laddercodec raises. Each one is a subclass of :class:`LaddercodecError`.

``decode()``, ``decode_program()``, ``encode()``, ``read_csv()``, ``write_csv()``,
``csv_rows()``, ``read_bundle()``, ``write_bundle()`` and ``check()`` raise a
``LaddercodecError`` for input they can't read or write.  Each class is a ``ValueError``,
so ``except ValueError`` catches every one of them.
``FieldError`` and ``AddressError`` are defined in :mod:`laddercodec.operands.errors`, and
they are subclasses of :class:`LaddercodecError` too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .codes import Code

if TYPE_CHECKING:
    from .operands.errors import FieldError, Reason
    from .operands.message import Parts


class LaddercodecError(ValueError):
    """The base class of every error that laddercodec raises for input it can't read or write.

    ``except LaddercodecError`` catches all of them, and so does ``except ValueError``.

    :meth:`message`, :meth:`short` and :meth:`detail` return the error's text with your
    names for the addresses in it.  Only these refusals show names: the refusals of
    ``Copy``, ``BlockCopy``, ``Fill``, ``Pack``, ``Unpack``, ``Timer``, ``Counter``,
    ``Shift``, ``ForLoop``, ``Drum``, ``Send``, ``Receive``, ``ModbusRtuTarget``,
    ``ModbusTcpTarget`` and ``ModbusAddress``, and the refusals of the address, operand
    and flag checks that other instructions share, such as the bank check on
    ``Coil.operand``.  Any other error ignores the names.
    """

    # The parts of the message (operands.message.Parts), for an error that keeps them.
    _parts: Any = None
    # The text added to the end of the message after it was built, such as a CSV location.
    _suffix: str = ""

    def message(self, names: Mapping[str, str] | None = None) -> str:
        """Return the error's text, with each address in ``names`` shown by its name.

        With ``names`` None or empty, return ``str(err)``.  Otherwise each address that
        ``names`` maps is replaced by its name.  CLICK's form of the value follows in
        parentheses when the two differ.  A value that holds an address is shown without
        quotes, even if no key of ``names`` is a CLICK address.  For the refusal ``err``
        that ``Copy(source="DS1", dest="C1")`` raises::

            str(err)
            # Copy.dest: 'C1' can't take 'DS1'; a numeric register copies to DS, DD, ...
            err.message({"C1": "Valve"})
            # Copy.dest: Valve (C1) can't take DS1; a numeric register copies to DS, DD, ...

        A range and a pointer are shown in the same way:

        - ``Valve1..Valve2 (C1..C2)`` when both ends have names.
        - ``Valve1..C2 (C1..C2)`` when only the start has a name.
        - ``DS[Ptr] (DS[DD1])`` when the pointer's index register has a name.

        A key of ``names`` may be in any form that CLICK reads, such as ``ds1`` or
        ``DS001``.  It matches the address in CLICK's display form.  A key that is not a
        CLICK address is ignored.  If two keys are the same address, the later key is used.
        A constant, a bank list and a limit are never replaced.  A CSV location stays at
        the end of the text.
        """
        named = self._named(names)
        parts = None if named is None else self._kept_parts()
        if parts is None:
            return str(self)
        return parts.text(named) + self._suffix

    def short(self, names: Mapping[str, str] | None = None) -> str:
        """Return the refused value and its rule, such as ``'C1' can't take 'DS1'``.

        The text has no ``Class.field:`` prefix, no explanation, no CLICK id and no CSV
        location.  ``names`` works as it does for :meth:`message`.  For an error that does
        not show names, return ``str(err)`` without its ``Class.field:`` prefix and without
        its CSV location.
        """
        parts = self._kept_parts()
        if parts is not None:
            return parts.short_text(self._named(names))
        text = str(self)
        if self._suffix and text.endswith(self._suffix):
            text = text[: -len(self._suffix)]
        field = getattr(self, "field", None)
        if isinstance(field, str) and text.startswith(f"{field}: "):
            text = text[len(field) + 2 :]
        return text

    def detail(self, names: Mapping[str, str] | None = None) -> str:
        """Return the explanation alone, such as ``a numeric register copies to DS, DD, ...``.

        If the error also tells you what to do, that sentence follows the explanation.
        ``names`` works as it does for :meth:`message`.  Return an empty string for a
        refusal that has no explanation, and for an error that does not show names.
        """
        parts = self._kept_parts()
        return "" if parts is None else parts.detail_text(self._named(names))

    def _kept_parts(self) -> Parts | None:
        from .operands.message import parts_of

        return parts_of(self)

    @staticmethod
    def _named(names: Mapping[str, str] | None) -> dict[str, str] | None:
        from .operands.message import named_addresses

        # Non-empty names drop the quotes, even if none of the keys is an address.
        return named_addresses(names) if names else None


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


class CsvReadError(LaddercodecError):
    """Raised when ``read_csv`` or ``read_bundle`` cannot read a CSV.

    ``read_csv`` raises it for a file that isn't UTF-8 text, and for a row, a token or a
    rung that it can't read.  Like every error that ``read_csv`` raises for a bad CSV, it
    has a :class:`~laddercodec.CsvLocation` as its ``location`` attribute.

    ``read_bundle`` raises it for the same reasons in any file of the bundle.  It also
    raises it when ``main.csv`` is missing, when CLICK refuses the name of a file in
    ``subroutines/`` as a subroutine name, when one of those names starts or ends with
    whitespace, and when two of them are equal with the case of A-Z ignored.  For a name
    that CLICK refuses, the ``CsvReadError`` copies the refusal's data in the same way as for a
    pin row, described next.

    Both functions raise it for a bad ``allow=``, before they read any file.  A bad
    ``allow=`` is an item that is not a code's name, a single string or bytes in place of a
    list, a value that you can't iterate over, or a non-empty ``allow=`` with
    ``unchecked=True``.  This ``CsvReadError`` has no ``location``.

    Some boxes, such as a counter, take inputs from pin rows below the box's own row.
    ``read_csv`` builds such a box from all of its rows.  If the box refuses a value at that
    step, the ``FieldError`` reaches you wrapped in a ``CsvReadError``, and ``except FieldError``
    does not catch it.  The ``CsvReadError`` copies the refusal's data.  ``field``, ``fields``,
    ``reason``, ``code`` and ``click_id`` are those of the first refusal, with the meanings
    they have on ``FieldError``.  ``errors`` holds every refusal for the box, and each is a
    ``FieldError`` with its own ``location``.  ``errors[0]`` is the wrapped ``FieldError``,
    which is also ``__cause__``.  It is not this exception.  A refusal of a value that a pin
    row sets is located at that pin's row.  Any other refusal is located at the box's own row.

    A ``CsvReadError`` that is not about a refused field has ``field`` and ``reason`` set to
    ``None``, an empty ``fields``, and ``errors == (self,)``.  A pin token that does not
    parse and a rung with no rows are two examples.  Such a ``CsvReadError`` has ``code`` and
    ``click_id`` set to ``None``, except in these two cases:

    - ``read_csv`` and ``read_bundle`` raise it for a rung that needs more than the 32 rows
      of a CLICK rung, in strict and in relaxed mode.  Its ``code`` is then
      ``layout-too-tall``, its ``click_id`` is ``None``, and its location is the rung's
      ``R`` row.
    - ``read_bundle`` raises it for two files in ``subroutines/`` whose names are equal when
      the case of A-Z is ignored.  Its ``code`` is then ``duplicate-subroutine-name``, and its
      ``click_id`` is ``GUI-036``.

    If you build a ``CsvReadError`` with ``refusal``, it copies its attributes from the refusal
    and ignores ``field``, ``code`` and ``click_id``.
    """

    field: str | None
    fields: tuple[str, ...]
    reason: Reason | None
    code: Code | None
    click_id: str | None
    errors: tuple[FieldError, ...] | tuple[CsvReadError]

    def __init__(
        self,
        *args: object,
        field: str | None = None,
        refusal: FieldError | None = None,
        code: Code | None = None,
        click_id: str | None = None,
    ) -> None:
        super().__init__(*args)
        if refusal is None:
            self.field = field
            self.fields = () if field is None else (field,)
            self.reason = None
            self.code = code
            self.click_id = click_id
            self.errors = (self,)
        else:
            self.field = refusal.field
            self.fields = refusal.fields
            self.reason = refusal.reason
            self.code = refusal.code
            self.click_id = refusal.click_id
            self.errors = refusal.errors
            # message(), short() and detail() render the refusal's parts.  They use them only
            # while this error's text is the refusal's text.
            self._parts = refusal._parts
            self._suffix = refusal._suffix


class CsvWriteError(LaddercodecError):
    """Raised when ``write_csv`` or ``csv_rows`` is given a rung that the CSV can't hold, or
    a bad ``stop=``.

    ``stop=`` must be ``"end"`` or ``"return"``.  ``write_csv`` builds every row before it
    opens the file.  If it raises ``CsvWriteError``, it has not created or changed the file.

    ``write_bundle`` raises it for a rung that the CSV can't hold, for two subroutines whose
    names are equal when the case of A-Z is ignored, for two subroutines whose files would be
    one file on a file system that ignores case, for a subroutine name that holds a control
    character, and for a path that it would write that exists and is of the wrong kind.  It
    raises before it writes any file.

    ``write_csv``, ``csv_rows`` and ``write_bundle`` raise it for a rung that needs more than
    the 32 rows of a CLICK rung.  The ``__cause__`` is then a :class:`LayoutError` with the
    code ``layout-too-tall``.

    ``code`` and ``click_id`` are ``None``, except in these two cases:

    - For a rung that needs more than 32 rows, ``code`` is ``layout-too-tall`` and
      ``click_id`` is ``None``.
    - For two subroutines whose names are equal when the case of A-Z is ignored, ``code`` is
      ``duplicate-subroutine-name`` and ``click_id`` is ``GUI-036``.
    """

    code: Code | None
    click_id: str | None

    def __init__(
        self, *args: object, code: Code | None = None, click_id: str | None = None
    ) -> None:
        super().__init__(*args)
        self.code = code
        self.click_id = click_id


class LayoutError(LaddercodecError):
    """Raised by :func:`~laddercodec.lay_out` for a circuit that CLICK can't hold or that
    laddercodec can't draw.

    ``code`` is a :class:`~laddercodec.Code` that says why:

    - ``layout-too-tall``: a rung needs more than 32 rows.
    - ``layout-too-wide``: a rung needs more than the 31 condition columns.
    - ``layout-cannot-draw``: two wires or two cells of the drawing would fall on one place.
    - ``layout-nop-split``: outputs meet only at the rail, and one of them is a NOP behind a
      contact, or all of them are NOPs.
    - ``output-above-box-inputs``: an output comes before a box whose pin is used, on that
      box's main input circuit.  Its ``click_id`` is ``C000A``.
    - ``shared-input-net``: an output comes after a box whose pin is used, on that box's
      main input circuit.  Its ``click_id`` is ``C000A``.

    ``click_id`` is ``None`` for the four ``layout-`` codes.  When ``write_csv`` can't lay
    out a rung, it raises :class:`~laddercodec.CsvWriteError`.  The ``__cause__`` of that error
    can be a ``LayoutError`` with one of these codes, or with the code of a ``check()``
    finding such as ``not-series-parallel``.  Its ``click_id`` is then CLICK's id when CLICK
    has one, such as ``C0001``.
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
