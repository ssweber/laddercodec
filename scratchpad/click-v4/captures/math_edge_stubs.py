"""Write stubs/math_edge.csv: Math literals at the edges of what we've seen natively.

Native captures only show decimal integers (``200`` -> ``H200``) and one hex constant
(``Ah`` -> ``UH10``).  Each rung here is a literal form whose internal spelling
(tags 0x6229 / 0x61FD) we are guessing.  In CLICK v4: paste, run Check Program and
note which rungs fail, copy back as ``math_edge-pasted``; then reopen every Math, hit
OK, copy back as ``math_edge-ok``.  Diffing the two shows CLICK's normalization rung
by rung, including the ones that didn't fail.

Rung n: contact C(1900+n), source DS401 / DD401 / DF401 / DH401, result
DS/DD/DF/DH(410+n).  Every address sits inside CLICK's range (C to 2000, DD to
1000, DF/DH to 500), so clicknick provisions all of them in the MDB.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER

HERE = Path(__file__).parent
WIDTH = len(CONDITION_COLUMNS)

# (id, expression, result prefix, mode)
CASES = [
    # decimal integers
    ("dec_int16_max", "DS401 + 32767", "DS", "decimal"),
    ("dec_int16_over", "DS401 + 32768", "DS", "decimal"),
    ("dec_int32_max", "DD401 + 2147483647", "DD", "decimal"),
    ("dec_int32_over", "DD401 + 2147483648", "DD", "decimal"),
    ("dec_zero", "DS401 * 0", "DS", "decimal"),
    ("dec_leading_zero", "DS401 + 007", "DS", "decimal"),
    ("dec_negative_rhs", "DS401 + -5", "DS", "decimal"),
    ("dec_negative_lhs", "-5 + DS401", "DS", "decimal"),
    ("dec_literal_only", "5 + 3", "DS", "decimal"),
    # decimal reals
    ("real_simple", "DF401 + 3.14", "DF", "decimal"),
    ("real_half", "DF401 * 0.5", "DF", "decimal"),
    ("real_no_leading_digit", "DF401 * .5", "DF", "decimal"),
    ("real_trailing_zero", "DF401 + 100.0", "DF", "decimal"),
    ("real_exp_neg", "DF401 * 1.0E-10", "DF", "decimal"),
    ("real_exp_lower", "DF401 * 1.5e+10", "DF", "decimal"),
    ("real_exp_no_point", "DF401 * 1E5", "DF", "decimal"),
    ("real_max_7_digits", "DF401 + 3.402823E+38", "DF", "decimal"),
    ("real_max_9_digits", "DF401 + 3.40282347E+38", "DF", "decimal"),
    ("real_8_digits", "DF401 + 16777215.0", "DF", "decimal"),
    ("real_pi", "DF401 * PI", "DF", "decimal"),
    ("real_func_literal", "SQRT ( 2.0 )", "DF", "decimal"),
    # hex
    ("hex_zero", "DH401 + 0h", "DH", "hex"),
    ("hex_one", "DH401 + 1h", "DH", "hex"),
    ("hex_ffff", "DH401 + FFFFh", "DH", "hex"),
    ("hex_over_16_bits", "DH401 + 10000h", "DH", "hex"),
    ("hex_lowercase", "DH401 + ffh", "DH", "hex"),
    ("hex_leading_zero", "DH401 + 00FFh", "DH", "hex"),
    ("hex_multi_digit", "DH401 AND AB59h", "DH", "hex"),
    ("hex_in_function", "LSH ( DH401 , 1h )", "DH", "hex"),
    ("hex_bare_decimal", "DH401 + 1", "DH", "hex"),
]

# Typed into CLICK's Math editor, a negative constant after an operator is refused
# (DS401 + -5, DF401 * -2.5) but accepted in parentheses (DS401 + ( -5 )), and
# -DS401 is redisplayed as - DS401.  These are those accepted display forms; pasted,
# the parenthesized ones still failed the check, so our internal form is wrong.
# Load, copy each formula into a fresh Math, copy back as math_neg-typed.
# Contacts C1941+, results (450+n).
NEG_CASES = [
    ("paren_add_literal", "DS401 + ( -5 )", "DS", "decimal"),
    ("paren_sub_literal", "DS401 - ( -5 )", "DS", "decimal"),
    ("paren_mul_literal", "DS401 * ( -5 )", "DS", "decimal"),
    ("paren_div_literal", "DS401 / ( -5 )", "DS", "decimal"),
    ("paren_real_literal", "DF401 * ( -2.5 )", "DF", "decimal"),
    ("paren_real_exp", "DF401 * ( -1.5E+10 )", "DF", "decimal"),
    ("lhs_literal", "-5 + DS401", "DS", "decimal"),
    ("neg_tag", "- DS401", "DS", "decimal"),
    ("paren_neg_tag", "DS401 * ( - DS402 )", "DS", "decimal"),
    # passed when pasted: controls
    ("neg_group", "- ( DS401 + 1 )", "DS", "decimal"),
    ("zero_minus_literal", "DS401 * ( 0 - 5 )", "DS", "decimal"),
    ("flipped_sub", "DS401 - 5", "DS", "decimal"),
]


def write(name: str, cases: list[tuple[str, str, str, str]], contact: int, result: int) -> None:
    rows: list[list[str]] = [list(CSV_HEADER)]
    for n, (case_id, expression, prefix, mode) in enumerate(cases, 1):
        token = f"math({expression},{prefix}{result + n},mode={mode})"
        cells = ["-"] * WIDTH
        cells[0] = f"C{contact + n}"
        body = token
        note = token
        if case_id in TYPED:
            body = f"math(DS401 + 1,{prefix}{result + n},mode={mode})"
            note = f"TYPE: {token}"
        rows += [["#", f"{name}__{case_id}"], ["#", note], ["R", *cells, body]]
    end = ["-"] * WIDTH
    rows.append(["R", *end, "end()"])
    path = HERE / "stubs" / f"{name}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    print(f"{path.name}: {len(cases)} math rungs + end")


# math_neg copy-back: DS401 * ( - DS402 ) fails even typed, so pyrung now writes a
# negation inside a formula as ( 0 - x ); reals are stored with an F prefix (F-2.5).
# All 8 pass the v4 check pasted.  Contacts C1961+, results (470+n).
NEG2_CASES = [
    ("zero_minus_tag_rhs", "DS401 * ( 0 - DS402 )", "DS", "decimal"),
    ("zero_minus_tag_lhs", "( 0 - DS401 ) * DS402", "DS", "decimal"),
    ("zero_minus_group", "DS401 - ( 0 - ( DS402 + 1 ) )", "DS", "decimal"),
    ("zero_minus_real", "DF401 * ( 0 - DF402 )", "DF", "decimal"),
    ("zero_minus_hex", "DH401 + ( 0h - DH402 )", "DH", "hex"),
    ("real_positive", "DF401 * 3.14", "DF", "decimal"),
    ("real_positive_exp", "DF401 * 1.5E+10", "DF", "decimal"),
    ("real_lhs_negative", "-2.5 * DF401", "DF", "decimal"),
]

# Math operands, visible (0x6888) and invisible (0x688C, the interiors of each range).
# Contacts C1971+, results (480+n).
OPERAND_CASES = [
    # spacing: written unspaced here, the encoder should space them
    ("spacing_add", "DS401+DS402", "DS", "decimal"),
    ("spacing_func_literal", "ABS(DS401)*2", "DS", "decimal"),
    ("spacing_sub_literal", "DS401-5", "DS", "decimal"),
    ("spacing_sign_tag", "-DS401", "DS", "decimal"),
    ("spacing_power_real", "DF401^2.5", "DF", "decimal"),
    # visible: one past the 68 operands v3's editor took; do v4's limits differ?
    ("ops_69", " + ".join(f"DS{n}" for n in range(401, 470)), "DD", "decimal"),
    # visible: register types the encoder does not recognize as operands yet (XD, YD)
    ("type_xd", "XD0 AND 1h", "DH", "hex"),
    ("type_xd_upper", "XD0u AND 1h", "DH", "hex"),
    ("type_yd", "YD1 AND 1h", "DH", "hex"),
    ("type_td_ctd_sd", "TD1 + CTD1 + SD1", "DD", "decimal"),
    # invisible: X/Y addresses are not contiguous; we list X017..X020 and X037..X100
    ("range_x_gap", "SUM ( X001 : X036 )", "DS", "decimal"),
    ("range_x_slots", "SUM ( X001 : X101 )", "DS", "decimal"),
    ("range_t_bits", "SUM ( T1 : T5 )", "DS", "decimal"),
    ("range_td", "MAX ( TD1 : TD5 )", "DD", "decimal"),
    ("range_xd", "MAX ( XD0 : XD3 )", "DH", "hex"),
    # invisible: exactly the 500 slots we write, in one range and split over two
    ("range_cap_500", "SUM ( DS1 : DS502 )", "DD", "decimal"),
    ("range_cap_two", "SUM ( DS1 : DS252 ) + SUM ( DS301 : DS552 )", "DD", "decimal"),
    # invisible: past our 500, the encoder refuses these; rungs are stand-ins, see TYPED
    ("range_over_501", "SUM ( DS1 : DS503 )", "DD", "decimal"),
    ("range_over_998", "SUM ( DS1 : DS1000 )", "DD", "decimal"),
    ("range_over_4498", "SUM ( DS1 : DS4500 )", "DD", "decimal"),
    ("range_over_5496", "SUM ( DS1 : DS4500 ) + SUM ( DD1 : DD1000 )", "DD", "decimal"),
]

#: Formulas to type in CLICK: the rung pastes as ``DS401 + 1``, its comment says what to type.
TYPED = {"range_over_501", "range_over_998", "range_over_4498", "range_over_5496"}

# The ranges math_operands had to type, now on the rung: our 5510-field form, never
# pasted before.  CLICK v4 only.  Contacts C1993+, results DD(510+n).
WIDE_CASES = [
    ("wide_501", "SUM ( DS1 : DS503 )", "DD", "decimal"),
    ("wide_998", "SUM ( DS1 : DS1000 )", "DD", "decimal"),
    ("wide_4498", "SUM ( DS1 : DS4500 )", "DD", "decimal"),
    ("wide_5496", "SUM ( DS1 : DS4500 ) + SUM ( DD1 : DD1000 )", "DD", "decimal"),
]

STUBS = {
    "math_wide": (WIDE_CASES, 1992, 510),
    "math_edge": (CASES, 1900, 410),
    "math_neg": (NEG_CASES, 1940, 450),
    "math_neg2": (NEG2_CASES, 1960, 470),
    "math_operands": (OPERAND_CASES, 1970, 480),
}

# Only the stubs named on the command line (default all): a copy-back saved under
# the same name overwrites the stub CSV, so don't regenerate one that's been used.
for stub_name in sys.argv[1:] or STUBS:
    write(stub_name, *STUBS[stub_name])
