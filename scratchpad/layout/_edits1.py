"""One-off: move convert_rung callers to its list[Rung] return."""

from pathlib import Path


def sub(path: str, old: str, new: str, count: int = 1) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == count, (path, old, s.count(old))
    p.write_text(s.replace(old, new), encoding="utf-8")


sub(
    "tests/test_coverage.py",
    "            converted.append(convert_rung(rung))\n",
    "            converted.extend(_args(r) for r in convert_rung(rung))\n",
)
sub(
    "tests/test_coverage.py",
    "        out_converted.append(convert_rung(rung))\n",
    "        out_converted.extend(_args(r) for r in convert_rung(rung))\n",
)
sub(
    "tests/test_coverage.py",
    "def _convert_program(\n",
    "def _args(rung: Rung) -> tuple[int, list[list[object]], list[object], str | None]:\n"
    "    return rung.logical_rows, list(rung.conditions), list(rung.instructions), rung.comment\n"
    "\n\n"
    "def _convert_program(\n",
)
sub(
    "devtools/coverage_golden.py",
    "            logical_rows, cond_rows, af_tokens, comment = convert_rung(rung)\n"
    "        except (ConvertError, NotImplementedError, ValueError) as exc:\n"
    "            raise ValueError(f\"Cannot encode {csv_path.name} rung {idx}: {exc}\") from exc\n"
    "        converted.append((logical_rows, cond_rows, af_tokens, comment))\n",
    "            laid_out = convert_rung(rung)\n"
    "        except (ConvertError, NotImplementedError, ValueError) as exc:\n"
    "            raise ValueError(f\"Cannot encode {csv_path.name} rung {idx}: {exc}\") from exc\n"
    "        converted.extend(\n"
    "            (r.logical_rows, r.conditions, r.instructions, r.comment) for r in laid_out\n"
    "        )\n",
)
sub(
    "devtools/operand_probe.py",
    "            logical, conditions, instructions, comment = ns.convert_rung(ns.parse_rows(rows))\n"
    "        except Exception as exc:\n"
    "            return error_text(exc), None\n"
    "        rung = ns.Rung(logical, conditions, instructions, comment)\n",
    "            got = ns.convert_rung(ns.parse_rows(rows))\n"
    "        except Exception as exc:\n"
    "            return error_text(exc), None\n"
    "        if isinstance(got, list):  # laddercodec lays the rung out: one Rung per CLICK rung\n"
    "            rung = got[0]\n"
    "            conditions, instructions = rung.conditions, rung.instructions\n"
    "        else:\n"
    "            logical, conditions, instructions, comment = got\n"
    "            rung = ns.Rung(logical, conditions, instructions, comment)\n",
)
sub(
    "tests/ladder/test_raw_height.py",
    "    logical_rows, conditions, instructions, comment = convert_rung(\n"
    "        _parse_single_rung_rows([[\"R\", *[\"-\"] * 31, token]])\n"
    "    )\n"
    "    return Rung(logical_rows, conditions, instructions, comment, None)\n",
    "    [rung] = convert_rung(_parse_single_rung_rows([[\"R\", *[\"-\"] * 31, token]]))\n"
    "    return rung\n",
)
print("ok")
