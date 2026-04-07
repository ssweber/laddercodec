from __future__ import annotations

import pytest

from laddercodec import Rung
from laddercodec.csv.writer import _validate_roundtrip, decoded_rung_to_rows
from laddercodec.instructions import Email, Home, Position, Velocity


@pytest.mark.parametrize(
    "instruction",
    [
        pytest.param(
            Email(
                tag_60a5="1",
                tag_6235="TEST",
                tag_6236="TEST",
                tag_6217="TEST",
                tag_622a="TEST",
                tag_607c="C1",
                tag_607b="C2",
                tag_607d="C3",
                tag_6083="DS1",
            ),
            id="email",
        ),
        pytest.param(
            Home(
                tag_6096="1",
                tag_6097="1",
                tag_609f="X004",
                tag_60a0="X005",
                tag_609c="1",
                tag_609d="1",
            ),
            id="home",
        ),
        pytest.param(
            Position(
                tag_6098="1",
                tag_609b="1",
                tag_609c="1",
                tag_609d="1",
            ),
            id="position",
        ),
        pytest.param(
            Velocity(
                tag_609b="1",
                tag_609c="1",
                tag_609d="1",
            ),
            id="velocity",
        ),
    ],
)
def test_validate_roundtrip_accepts_equivalent_raw_instruction(
    instruction: Email | Home | Position | Velocity,
) -> None:
    rung = Rung(
        logical_rows=1,
        conditions=[["-"] * 31],
        instructions=[instruction],
        comment=None,
        comment_rtf=None,
    )

    _validate_roundtrip(rung, decoded_rung_to_rows(rung))
