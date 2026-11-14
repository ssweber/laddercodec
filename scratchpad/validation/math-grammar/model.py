"""Executable model of the CLICK v4 Math dialog OK path, as read from Inst_Math.dll.

check(text, hexmode) -> dict(tpl_disp, disp, tpl_int, int) or raises Refused(code).
Run as a script: re-derive the stored views of every Math blob in fixtures.json from its
stored display formula and compare.
"""

import json
import math
import re
import struct
import sys

KEYWORDS = {
    "(": 3, ")": 4, "[": 5, "]": 6, "SUM": 7, "SIN": 8, "ASIN": 9, "LOG": 10, "RAD": 11,
    "COS": 12, "ACOS": 13, "SQRT": 14, "DEG": 15, "TAN": 16, "ATAN": 17, "LN": 18, "PI": 19,
    "/": 20, "*": 21, "-": 22, "+": 23, "^": 24, "MOD": 25, "AND": 26, "OR": 27, "XOR": 28,
    "LSH": 29, "RSH": 30, "LRO": 31, "RRO": 32, ",": 33, ":": 34, ".": 35, "MAX": 39,
    "MIN": 40, "MDN": 41, "AVG": 42, "RAND": 43, "ABS": 44,
}
WS, CONST, ADDR, PTR = 2, 36, 37, 38
TRIG = set(range(8, 19))
BINOP = set(range(20, 29))
SHIFT = {29, 30, 31, 32}
BANKS = ["XD", "X", "YD", "Y", "TXT", "TD", "T", "CTD", "CT", "C", "SC", "SD", "DD", "DH", "DF", "DS"]
BIT_BANKS = {"X", "Y", "C", "SC", "T", "CT"}
ADDR_RE = re.compile(r"^(XD|YD|TXT|TD|CTD|CT|SC|SD|DD|DH|DF|DS|X|Y|T|C)(\d+)(U?)$")


class Refused(Exception):
    pass


def is_address(t):
    # stand-in for baseEx IsAddress (not read): bank prefix + digits (+u on XD/YD)
    m = ADDR_RE.match(t.upper())
    return bool(m) and (m.group(3) == "" or m.group(1) in ("XD", "YD"))


def is_float(s):
    if not s:
        return False
    t = s[1:] if s[0] == "-" else s
    t = t.upper().strip()
    try:
        float(t)
    except ValueError:
        return False
    return re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)(E[+-]?\d+)?|[+-]?(INF|INFINITY|NAN)", t) is not None


def tokenize(text):
    """Pass 1 (split on + - * / ^, whitespace runs, [ ]; <...> whole; float prefix rule)
    plus a stand-in for passes 2-4 (split ( ) , :)."""
    out, cur, i = [], "", 0
    seps = set("+-*/^[](),:")
    while i < len(text):
        ch = text[i]
        if ch == "<":
            j = text.find(">", i)
            j = len(text) - 1 if j < 0 else j
            if cur:
                out.append(cur)
                cur = ""
            out.append(text[i : j + 1])
            i = j + 1
            continue
        if (cur == "" or cur.isdigit()) and ch in ".Ee" and (cur or ch == "."):
            start = i - len(cur)
            m = re.match(r"(\d+\.?\d*|\.\d+)([Ee][+-]?\d+)?", text[start:])
            if m:
                out.append(m.group(0))
                cur = ""
                i = start + len(m.group(0))
                continue
        if ch in " \t":
            if cur:
                out.append(cur)
                cur = ""
            j = i
            while j < len(text) and text[j] in " \t":
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if ch in seps:
            if cur:
                out.append(cur)
                cur = ""
            out.append(ch)
            i += 1
            continue
        cur += ch
        i += 1
    if cur:
        out.append(cur)
    return out


def classify(toks):
    types = []
    for k, t in enumerate(toks):
        u = t.upper()
        if u in KEYWORDS:
            toks[k] = u
            types.append(KEYWORDS[u])
        elif t.strip(" \t") == "":
            types.append(WS)
        elif is_address(u) or (t.startswith("<") and t.endswith(">")):
            if not t.startswith("<"):
                toks[k] = u[:-1] + "u" if u.endswith("U") else u
            types.append(ADDR)
        else:
            types.append(0)
    return types


def nxt(types, i):
    j = i + 1
    while j < len(types) and types[j] == WS:
        j += 1
    return j


def prv(types, i):
    j = i - 1
    while j >= 0 and types[j] == WS:
        j -= 1
    return j


def paren_check(types):
    depth = 0
    for t in types:
        if t == 3:
            depth += 1
            if depth > 8:
                raise Refused("OBJ-1010")
        elif t == 4:
            depth -= 1
            if depth < 0:
                raise Refused("OBJ-1004")
    if depth > 0:
        raise Refused("OBJ-1005")


def exponent_rejoin(toks, types):
    k = 0
    while k < len(toks):
        if types[k] == 0:
            toks[k] = toks[k].upper()
        if types[k] == 0 and toks[k].upper().endswith("E") and k + 2 < len(toks) and toks[k + 1] in "+-" and types[k + 2] == 0:
            toks[k] = toks[k] + toks[k + 1] + toks[k + 2].upper()
            del toks[k + 1 : k + 3]
            del types[k + 1 : k + 3]
        k += 1


def unary_merge(toks, types):
    k = 0
    while k < len(toks):
        p = prv(types, k)
        if types[k] in (22, 23) and (p < 0 or types[p] in (3, 33)):
            n = nxt(types, k)
            if n < len(toks) and types[n] == 0:
                cand = toks[n].upper()
                if cand.endswith("H"):
                    cand = cand[:-1]
                if is_float(cand):
                    toks[k] = toks[k] + "".join(toks[k + 1 : n + 1])
                    types[k] = 0
                    del toks[k + 1 : n + 1]
                    del types[k + 1 : n + 1]
        k += 1


def convert(toks, types, hexmode):
    for k, t in enumerate(toks):
        if types[k] != 0:
            continue
        s = t.replace(" ", "").replace("\t", "")
        if not hexmode:
            if set(s) <= set("0123456789+-"):
                try:
                    v = int(s) if re.fullmatch(r"[+-]?\d+", s) else None
                except ValueError:
                    v = None
                if v is None:
                    raise Refused("OBJ-1009")
                low = struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]
                r = ("+" if s.startswith("+") else "") + str(low)
                if len(r) != len(s):
                    raise Refused("OBJ-1009")
                toks[k] = ("H" if -32768 <= v <= 32767 else "W") + s
                types[k] = CONST
            elif is_float(s):
                d = float(s)
                if math.isinf(d) or (not math.isnan(d) and abs(d) > 3.4028234663852886e38):
                    raise Refused("OBJ-1009")
                toks[k] = "F" + s
                types[k] = CONST
        else:
            u = s.upper()
            h = u.find("H")
            if h >= 0:
                u = u[:h] + u[h + 1 :]
            if u and re.fullmatch(r"[0-9A-F]+", u):
                if len(u) >= 5 or int(u, 16) > 0xFFFF:
                    raise Refused("OBJ-1009")
                toks[k] = "UH" + str(int(u, 16))
                types[k] = CONST


def leftover(toks, types):
    for k, t in enumerate(types):
        if t in (5, 6):
            raise Refused("OBJ-1001 bracket")
        if t == 0 and not toks[k].startswith("<?"):
            raise Refused("OBJ-1001 word")


def mode_check(types, hexmode):
    bad = {8, 9, 10, 11, 44, 12, 13, 14, 15, 16, 17, 18, 19, 24} if hexmode else {26, 27, 28, 29, 30, 31, 32}
    if any(t in bad for t in types):
        raise Refused("OBJ-1006")


OPERAND_START = {3, 7, *TRIG, 19, CONST, ADDR, 5, 6, 39, 40, 41, 42, 43, 44}


def grammar(toks, types):
    n = len(types)
    i = 0
    while i < n:
        t = types[i]
        j = nxt(types, i)
        follow = types[j] if j < n else None
        if t in (WS, 35):
            i += 1
            continue
        if t in (0, 1, 5, 6):
            raise Refused("OBJ-1001 type")
        if t == 3 and follow in {24, 21, 20, 25, 26, 27, 28, 33, 34, 35, 4, 5, 6}:
            raise Refused("OBJ-1001 after (")
        if t == 4 and follow in {3, *TRIG, 19, 7, 29, 30, 31, 32, CONST, ADDR, 35, 5, 6, 39, 40, 41, 42, 43, 44}:
            raise Refused("OBJ-1001 after )")
        if t in BINOP and follow in {4, *BINOP, 33, 34, 35, 5, 6}:
            raise Refused("OBJ-1001 after op")
        if t == CONST and follow in OPERAND_START - {6} | {6}:
            raise Refused("OBJ-1001 after const")
        if t == ADDR:
            if follow in OPERAND_START:
                raise Refused("OBJ-1001 after addr")
            bank = ADDR_RE.match(toks[i].upper())
            if bank and bank.group(1) in BIT_BANKS:
                raise Refused("OBJ-1002 bit address")
        if t == 19 and follow in {7, *TRIG, 19, CONST, ADDR, 33, 34, 35, 5, 6, 39, 40, 41, 42, 43, 44}:
            raise Refused("OBJ-1001 after PI")
        if t in TRIG:
            if follow != 3:
                raise Refused("OBJ-1001 trig needs (")
            depth, k, bal = 0, j, 0
            while k < n:
                depth += types[k] == 3
                depth -= types[k] == 4
                bal += {7: -1, 33: 1, 34: 1}.get(types[k], 0)
                if depth == 0:
                    break
                k += 1
            if bal:
                raise Refused("OBJ-1001 comma in trig")
        if t in SHIFT or t == 43:
            # F ( a , b ): a in {addr, ptr} (RAND: also const); b in {const, addr, ptr}
            seq, k = [], j
            for want in ("(", "a", ",", "b", ")"):
                if k >= n:
                    raise Refused("OBJ-1001 shape")
                seq.append(types[k])
                k = nxt(types, k)
            first_ok = {ADDR, PTR} if t in SHIFT else {CONST, ADDR, PTR}
            if seq[0] != 3 or seq[1] not in first_ok or seq[2] != 33 or seq[3] not in {CONST, ADDR, PTR} or seq[4] != 4:
                raise Refused("OBJ-1001 shape")
            i = prv(types, k) + 1
            continue
        if t in (7, 39, 40, 41, 42):
            # SUM/MAX/MIN/MDN/AVG handlers not read in detail: accept F ( a : b ), skip it
            seq, k = [], j
            for _ in range(5):
                if k >= n:
                    raise Refused("OBJ-1001 range shape")
                seq.append(types[k])
                k = nxt(types, k)
            if seq[0] != 3 or seq[1] != ADDR or seq[2] != 34 or seq[3] != ADDR or seq[4] != 4:
                raise Refused("OBJ-1001 range shape (model guess)")
            i = prv(types, k) + 1
            continue
        i += 1
    sig = [t for t in types if t != WS]
    if sig and sig[0] in {4, 5, 6, 20, 21, 24, 25, 26, 27, 28, 33, 34, 35}:
        raise Refused("OBJ-1001 first")
    if sig and sig[-1] not in {4, 6, 19, CONST, ADDR, PTR}:
        raise Refused("OBJ-1001 last")


def show_const(c):
    for p in ("UH", "UW", "H", "W", "F"):
        if c.startswith(p):
            body = c[len(p) :]
            if p in ("UH", "UW"):
                return "%Xh" % int(body)
            return body
    return c


def display(toks, types, template):
    parts = []
    for t, ty in zip(toks, types):
        if ty == WS:
            continue
        if ty == ADDR:
            parts.append("@" if template else t)
        elif ty == CONST:
            parts.append(show_const(t))
        else:
            parts.append(t)
    return " ".join(parts)


def internal(toks, types, template, addrs):
    sig = [(t.replace(" ", ""), ty) for t, ty in zip(toks, types) if ty != WS]
    it = iter(addrs)
    vals = []
    for t, ty in sig:
        if ty == ADDR:
            a = t if not t.startswith("<") else next(it, t)
            vals.append(("@" if template else a, ty))
        else:
            vals.append((t, ty))
    out = []
    k = 0
    while k < len(vals):
        t, ty = vals[k]
        if ty in SHIFT or ty == 43:
            # F ( a , b ) -> a # F # b ; the ( , ) slots are emptied
            out.extend([vals[k + 2][0], t, vals[k + 4][0], ""])
            k += 6
            continue
        out.append(t)
        k += 1
    s = ""
    for idx, t in enumerate(out):
        if t == "":
            continue
        s += t
        if idx != len(out) - 1:
            s += "#"
    # final strip of a trailing '#' tests the char past the end (bug): never strips
    if len(s) > 270:
        raise Refused("OBJ-1008")
    return s


def check(text, hexmode, addrs=()):
    toks = tokenize(text)
    types = classify(toks)
    paren_check(types)
    if not hexmode:
        exponent_rejoin(toks, types)
        unary_merge(toks, types)
    convert(toks, types, hexmode)
    leftover(toks, types)
    mode_check(types, hexmode)
    grammar(toks, types)
    return {
        "tpl_disp": display(toks, types, True),
        "disp": display(toks, types, False),
        "tpl_int": internal(toks, types, True, addrs),
        "int": internal(toks, types, False, addrs),
    }


def main():
    recs = json.load(open(sys.argv[1], encoding="utf-8"))
    seen = set()
    ok = bad = 0
    for r in recs:
        hexmode = r.get("hex") == "-1"
        native = (r.get("h09"), r.get("h0a")) == (1, 3)
        key = (r["disp"], r["tpl_int"], r["int"], hexmode)
        dup = key in seen
        seen.add(key)
        addrs = [p for p in r["int"].split("#") if ADDR_RE.match(p.upper())]
        try:
            got = check(r["disp"], hexmode, addrs)
        except Refused as e:
            got = {"error": str(e)}
        want = {k: r[k] for k in ("tpl_disp", "disp", "tpl_int", "int")}
        if got == want:
            ok += 1
        else:
            bad += 1
            if not dup:
                print(("NATIVE " if native else "encoder ") + r["file"].split("fixtures")[-1])
                print("   want", want)
                print("   got ", got)
    print(f"match {ok}, differ {bad}, total {ok + bad}, unique {len(seen)}")


if __name__ == "__main__":
    main()
