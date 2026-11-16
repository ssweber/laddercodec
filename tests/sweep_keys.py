"""What the field sweeps key their exemptions on, shared by ``test_blank_missing`` and
``test_long_digits``."""

from __future__ import annotations

from typing import Any


def kind_of(inst: Any, attr: str) -> str | None:
    """The OutVariant or Drum kind of ``inst``, ``None`` for a class without one.

    A drum's ``jump_target`` is checked only while its jump is on, so its kind carries the
    jump: ``"event, jump off"``.
    """
    kind = getattr(inst, "kind", None) or getattr(inst, "drum_kind", None)
    if kind is not None and attr == "jump_target":
        return f"{kind}, jump {'on' if inst.jump_enabled else 'off'}"
    return kind
