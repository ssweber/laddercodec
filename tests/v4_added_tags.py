"""The fields that CLICK v4 adds to a blob that the encoder writes in v3's form."""

from __future__ import annotations

#: Fields that v4 adds to a blob that the encoder writes in v3's form, by class. v4 accepts
#: both forms on paste.
V4_ADDED_TAGS: dict[str, frozenset[int]] = {
    "Drum": frozenset({0x6891, 0x428A, 0x6068}),
    # v4 writes every Out in its OutVariant shape: pulse/timer fields, all blank or 0.
    "Out": frozenset({0x60B3, 0x60B4, 0x60B5, 0x60B6, 0x1246, 0x1247, 0x21F9, 0x2248, 0x20CA}),
}
