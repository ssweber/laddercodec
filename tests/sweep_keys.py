"""The kind that the field sweeps use in the keys of their exemption tables.

``test_blank_missing``, ``test_long_digits`` and ``csv/test_blank_args`` share it."""

from __future__ import annotations

from typing import Any


def kind_of(inst: Any, attr: str) -> str | None:
    """Return the ``kind`` field of ``inst``, or ``None`` if its class has no ``kind``.

    For the ``jump_step`` field, the returned kind also says whether the jump is on, as in
    ``"event_drum, jump off"``.  A drum checks its ``jump_step`` only while its jump is on.
    """
    kind = getattr(inst, "kind", None)
    if kind is not None and attr == "jump_step":
        return f"{kind}, jump {'on' if inst.jump_enabled else 'off'}"
    return kind
