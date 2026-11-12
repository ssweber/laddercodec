"""Run the model on probe formulas (dialog predictions)."""

import sys

sys.path.insert(0, sys.argv[1])
from model import Refused, check  # noqa: E402

PROBES = [
    ("DH1 + 7", True), ("DH1 + FACE", True), ("DH1 + 10", True), ("DH1 + C1", True),
    ("DH1 + 1Eh", True), ("DH1 + 3E8h", True), ("DH1 + 0Eh", True), ("DH1 + H7", True),
    ("DH1 + 7H7H", True), ("DH1 + H", True), ("DH1 + -Ah", True), ("DH1 + 00h", True),
    ("DH1 + 0FFFFh", True), ("DH1 ^ 2h", True), ("ABS ( DH1 )", True),
    ("LSH ( 1h , 2h )", True), ("LSH ( DH1 + 1h , 2h )", True), ("LSH(DH1,1h)", True),
    ("DS1 * -5", False), ("DS1 * ( -5 )", False), ("( - 5 )", False), ("( +5 )", False),
    ("DS1 + 007", False), ("DS1 + -0", False), ("-0", False), ("1e5", False), ("DS1 + 1 0", False),
    ("RAND ( 1 , -5 )", False), ("RAND ( DS1 + 1 , 10 )", False), ("SIN ( MAX ( DF1 : DF3 ) )", False),
    ("SIN ( SUM ( DF1 : DF3 ) )", False), ("SIN DF1", False), ("PI ( 2 )", False), ("DS1 + C1", False),
    ("DS1 + TXT1", False), ("sum ( ds1 : ds3 )", False), ("DS1\t+\t1", False), ("DS1 + NAN", False),
    ("DS1 + 1.", False), ("DS1 + 32768", False), ("DS1 + 2147483648", False), ("DS1 AND 1", False),
    ("- DS1", False), ("DS1 +", False), ("MAX ( DS1 , DS2 )", False),
]
for text, hexmode in PROBES:
    try:
        r = check(text, hexmode)
        out = f"{r['disp']!r}  int={r['int']!r}"
    except Refused as e:
        out = f"REFUSED {e}"
    print(f"{'hex' if hexmode else 'dec'} {text!r:32} -> {out}")
