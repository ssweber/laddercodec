"""Compare this capture's rung cell positions/types with extracted project XML.

Obfuscated field names below were observed in Productivity Suite 4.7.2.4.
This is a research check, not a version-independent clipboard decoder.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from read_java_stream import Reader

capture, project_xml = map(Path, sys.argv[1:])
reader = Reader(capture.read_bytes())
assert reader.take(4) == bytes.fromhex("aced0005")
root = reader.read()
assert reader.pos == len(reader.data)


def field(obj, suffix):
    return reader.resolve(
        next(value for key, value in obj["fields"].items() if key.endswith("." + suffix))
    )


def vector(obj):
    return field(obj, "elementData")["values"][: field(obj, "elementCount")]


project = ET.parse(project_xml).getroot()


def integer(node, name):
    text = node.findtext(name)
    if text is None:
        raise ValueError(f"Missing {name}")
    return int(text)


xsi_type = "{http://www.w3.org/2001/XMLSchema-instance}type"
results = []
for rung_ref in vector(field(root, "bue")):
    rung = reader.resolve(rung_ref)
    number, subnumber = field(rung, "flQ"), field(rung, "flR")
    xml = next(
        row
        for row in project.findall("rungs")
        if integer(row, "rungNumber") == number and integer(row, "subRungNumber") == subnumber
    )
    expected = {}
    for element in xml.findall("elements"):
        instruction = element.find("instruction")
        kind = instruction.attrib[xsi_type].lower() if instruction is not None else None
        position = integer(element, "position")
        for i in range(integer(element, "repeat") + 1):
            expected[position + i] = (
                integer(element, "elementType"),
                integer(element, "subType"),
                kind,
            )
    actual = {}
    cells = vector(field(rung, "flS"))
    for position, ref in enumerate(cells):
        cell = reader.resolve(ref)
        if cell is None:
            continue
        instruction = field(cell, "gV")
        kind = instruction["class"].split(".")[-1].replace("_", "").lower() if instruction else None
        actual[position] = (field(cell, "flJ"), field(cell, "flK"), kind)
    assert actual == expected, (number, subnumber, actual, expected)
    assert field(rung, "aEL") == (xml.findtext("comment") or "")
    results.append(
        {
            "rung": number,
            "subrung": subnumber,
            "vector_length": len(cells),
            "nonempty_cells": len(actual),
            "cells_match": True,
            "comment_matches": True,
        }
    )
report = {
    "capture": str(capture),
    "project_xml": str(project_xml),
    "rows": results,
    "scope": "Matches positions, element types, wire subtypes, instruction kinds, and comments; not every operand field.",
}
(capture.parent / f"comparison-{project_xml.parent.parent.name}.json").write_text(
    json.dumps(report, indent=2), encoding="utf-8"
)
print(json.dumps(report, indent=2))
