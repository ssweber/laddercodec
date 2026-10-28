"""Write stubs/math_edge.csv: Math literals at the edges of what we've seen natively.

Native captures only show decimal integers (``200`` -> ``H200``) and one hex constant
(``Ah`` -> ``UH10``).  Each rung here is a literal form whose internal spelling
(tags 0x6229 / 0x61FD) we are guessing.  In CLICK v4: paste, run Check Program and
note which rungs fail, copy back as ``math_edge-pasted``; then reopen every Math, hit
OK, copy back as ``math_edge-ok``.  Diffing the two shows CLICK's normalization rung
by rung, including the ones that didn't fail.

Rung n: contact C(2300+n), source DS2301 / DD2301 / DF2301 / DH2301, result
DS/DD/DF/DH(2400+n).
"""

from __future__ import annotations

import csv
from pathlib import Path

from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER

HERE = Path(__file__).parent
WIDTH = len(CONDITION_COLUMNS)

# (id, expression, result prefix, mode)
CASES = [
    # decimal integers
    ("dec_int16_max", "DS2301 + 32767", "DS", "decimal"),
    ("dec_int16_over", "DS2301 + 32768", "DS", "decimal"),
    ("dec_int32_max", "DD2301 + 2147483647", "DD", "decimal"),
    ("dec_int32_over", "DD2301 + 2147483648", "DD", "decimal"),
    ("dec_zero", "DS2301 * 0", "DS", "decimal"),
    ("dec_leading_zero", "DS2301 + 007", "DS", "decimal"),
    ("dec_negative_rhs", "DS2301 + -5", "DS", "decimal"),
    ("dec_negative_lhs", "-5 + DS2301", "DS", "decimal"),
    ("dec_literal_only", "5 + 3", "DS", "decimal"),
    # decimal reals
    ("real_simple", "DF2301 + 3.14", "DF", "decimal"),
    ("real_half", "DF2301 * 0.5", "DF", "decimal"),
    ("real_no_leading_digit", "DF2301 * .5", "DF", "decimal"),
    ("real_trailing_zero", "DF2301 + 100.0", "DF", "decimal"),
    ("real_exp_neg", "DF2301 * 1.0E-10", "DF", "decimal"),
    ("real_exp_lower", "DF2301 * 1.5e+10", "DF", "decimal"),
    ("real_exp_no_point", "DF2301 * 1E5", "DF", "decimal"),
    ("real_max_7_digits", "DF2301 + 3.402823E+38", "DF", "decimal"),
    ("real_max_9_digits", "DF2301 + 3.40282347E+38", "DF", "decimal"),
    ("real_8_digits", "DF2301 + 16777215.0", "DF", "decimal"),
    ("real_pi", "DF2301 * PI", "DF", "decimal"),
    ("real_func_literal", "SQRT ( 2.0 )", "DF", "decimal"),
    # hex
    ("hex_zero", "DH2301 + 0h", "DH", "hex"),
    ("hex_one", "DH2301 + 1h", "DH", "hex"),
    ("hex_ffff", "DH2301 + FFFFh", "DH", "hex"),
    ("hex_over_16_bits", "DH2301 + 10000h", "DH", "hex"),
    ("hex_lowercase", "DH2301 + ffh", "DH", "hex"),
    ("hex_leading_zero", "DH2301 + 00FFh", "DH", "hex"),
    ("hex_multi_digit", "DH2301 AND AB59h", "DH", "hex"),
    ("hex_in_function", "LSH ( DH2301 , 1h )", "DH", "hex"),
    ("hex_bare_decimal", "DH2301 + 1", "DH", "hex"),
]


def main() -> None:
    rows: list[list[str]] = [list(CSV_HEADER)]
    for n, (case_id, expression, prefix, mode) in enumerate(CASES, 1):
        token = f"math({expression},{prefix}{2400 + n},mode={mode})"
        cells = ["-"] * WIDTH
        cells[0] = f"C{2300 + n}"
        rows += [["#", f"math_edge__{case_id}"], ["#", token], ["R", *cells, token]]
    end = ["-"] * WIDTH
    rows.append(["R", *end, "end()"])
    path = HERE / "stubs" / "math_edge.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    print(f"{path.name}: {len(CASES)} math rungs + end")


main()
