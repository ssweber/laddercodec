from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.dom import minidom
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import pytest

from laddercodec.productivity import decode_program, decode_project, encode_project

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/productivity/two-button-latch"
NATIVE = FIXTURES / "project-4.7.2.4.adpro"


def archive(entries, header=b"\xad\xc0\x30\x02", checksum=True):
    """Synthetic framing helper, not an application-generated golden."""
    stream = BytesIO()
    stream.write(header)
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as target:
        for name, content in entries:
            target.writestr(name, content)
        if checksum:
            target.writestr("program.sha256", sha256(b"".join(b for _, b in entries)).digest())
    return stream.getvalue()


def test_native_project_noop_is_byte_identical():
    raw = NATIVE.read_bytes()
    project = decode_project(raw)
    assert project.header.hex() == "adc03002"
    assert len(project.entries) == 13
    assert project.program_names == ("task/T1.rll",)
    assert project.read("program.sha256").hex() == (
        "e4a463e0b9136b575bea729992c6888c9530b9a487a11841de136adba2f69cb0"
    )
    assert encode_project(project) == raw


def test_native_ladder_inspection():
    project = decode_project(NATIVE.read_bytes())
    program = decode_program(project.read("task/T1.rll"))
    row = program.rungs[0]
    assert (row.number, row.subrung, row.disabled) == (0, 0, False)
    assert "Two Button Latch Example Program" in row.comment
    assert [(e.position, e.instruction.kind) for e in row.elements if e.instruction] == [
        (1, "adcInstNO"),
        (3, "adcInstNO"),
        (5, "adcInstNC"),
        (21, "adcInstOUT"),
    ]
    first = next(e.instruction for e in row.elements if e.instruction)
    assert first.tags[0].name == "Button 1"
    assert first.tags[0].system_id == "C-000001"
    assert first.tags[0].data_type == 11
    assert list(row.elements[6].positions) == list(range(6, 20))
    timer = program.rungs[1].elements[-1].instruction
    assert timer is not None and timer.kind == "adcInstSTMR"
    document = minidom.parseString(timer.xml)
    assert document.getElementsByTagName("constText")[0].firstChild.data == "3"
    assert document.getElementsByTagName("timeBase")[0].firstChild.data == "second"
    assert program.xml == project.read("task/T1.rll")


def test_edit_timer_preserves_opaque_entries_and_updates_digest():
    original = decode_project(NATIVE.read_bytes())
    document = original.xml("task/T1.rll")
    # DOM changes are independent until explicitly applied.
    document.getElementsByTagName("constText")[0].firstChild.data = "7"
    const = document.getElementsByTagName("constValue")[0]
    const.getElementsByTagName("value")[0].firstChild.data = "7"
    updated = original.replace_xml("task/T1.rll", document)
    encoded = encode_project(updated)
    result = decode_project(encoded)
    assert original.read("task/T1.rll") != result.read("task/T1.rll")
    assert original.read("program.sha256") != result.read("program.sha256")
    assert b"<constText>7</constText>" in result.read("task/T1.rll")
    for entry in original.entries:
        if entry.name not in ("task/T1.rll", "program.sha256"):
            assert result.read(entry.name) == entry.data
    with ZipFile(BytesIO(encoded)) as z:
        assert z.testzip() is None
        digest = sha256()
        for name in z.namelist():
            if name != "program.sha256":
                digest.update(z.read(name))
        assert z.read("program.sha256") == digest.digest()


def test_legacy_native_entries_in_synthetic_container():
    folder = FIXTURES / "legacy-3.12.1"
    entries = [
        (p.relative_to(folder).as_posix(), p.read_bytes())
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    ]
    raw = archive(entries, bytes.fromhex("adc03000"), checksum=False)
    project = decode_project(raw)
    assert encode_project(project) == raw
    assert (
        decode_program(project.read("task/T1.rll")).rungs[0].elements[1].instruction.kind
        == "adcInstNO"
    )
    edited = project.replace_entry(
        "task/T1.rll", project.read("task/T1.rll").replace(b"Button 1", b"Start")
    )
    result = decode_project(encode_project(edited))
    assert result.header == project.header
    assert "program.sha256" not in [e.name for e in result.entries]
    assert b"Start" in result.read("task/T1.rll")


def test_unknown_entries_and_zip_metadata_survive_edit():
    stream = BytesIO()
    stream.write(bytes.fromhex("adc03000"))
    info = ZipInfo("future/opaque.bin", (2020, 1, 2, 3, 4, 6))
    info.compress_type = ZIP_STORED
    info.comment = b"entry-comment"
    info.extra = b"\xfe\xca\x02\x00ok"
    info.external_attr = 0x12340000
    with ZipFile(stream, "w") as z:
        z.comment = b"archive-comment"
        z.writestr(info, b"\x00\xffopaque")
        z.writestr("editable.xml", b"<thing/>")
    project = decode_project(stream.getvalue()).replace_entry("editable.xml", b"<changed/>")
    with ZipFile(BytesIO(encode_project(project))) as z:
        actual = z.getinfo(info.filename)
        assert z.comment == b"archive-comment"
        assert z.read(info.filename) == b"\x00\xffopaque"
        for attribute in ("date_time", "compress_type", "comment", "extra", "external_attr"):
            assert getattr(actual, attribute) == getattr(info, attribute)


def test_namespace_and_unknown_instruction_preservation():
    source = b"""<Program xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:v="urn:future">
<rungs><comment>Unicode: \xe2\x98\x83</comment><disabled>false</disabled>
<rungNumber>0</rungNumber><subRungNumber>0</subRungNumber>
<elements><position>1</position><repeat>0</repeat><elementType>0</elementType><subType>0</subType>
<instruction xsi:type="v:futureInstruction"><future xsi:type="v:Novel">42</future></instruction>
</elements></rungs></Program>"""
    project = decode_project(archive([("task/T1.rll", source)]))
    program = decode_program(source)
    assert program.rungs[0].comment == "Unicode: \u2603"
    instruction = program.rungs[0].elements[0].instruction
    assert instruction.kind == "v:futureInstruction"
    doc = minidom.parseString(instruction.xml)
    assert doc.documentElement.getAttribute("xmlns:v") == "urn:future"
    edited = project.replace_xml("task/T1.rll", project.xml("task/T1.rll"))
    xml = decode_project(encode_project(edited)).read("task/T1.rll")
    assert b'xmlns:v="urn:future"' in xml
    assert b'xsi:type="v:Novel"' in xml


def test_checksum_corruption_is_rejected():
    raw = archive([("task/T1.rll", b"<Program/>")])
    with ZipFile(BytesIO(raw)) as z:
        entries = [(n, b"<Changed/>" if n.endswith(".rll") else z.read(n)) for n in z.namelist()]
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        decode_project(archive(entries, checksum=False))


def test_crc_corruption_is_rejected():
    stream = BytesIO()
    stream.write(bytes.fromhex("adc03000"))
    with ZipFile(stream, "w", compression=ZIP_STORED) as z:
        z.writestr("program.prj", b"unique-payload")
    broken = stream.getvalue().replace(b"unique-payload", b"broken-payload")
    with pytest.raises(BadZipFile, match="CRC"):
        decode_project(broken)


@pytest.mark.parametrize("header", [b"", b"PK\x03\x04", bytes.fromhex("adc03003")])
def test_unknown_header_is_rejected(header):
    with pytest.raises(ValueError, match="header"):
        decode_project(header + b"invalid")


def test_missing_checksum_is_rejected():
    with pytest.raises(ValueError, match="presence disagree"):
        decode_project(archive([("program.prj", b"<Project/>")], checksum=False))


def test_duplicate_names_are_rejected():
    with pytest.warns(UserWarning, match="Duplicate name"):
        raw = archive([("same", b"a"), ("same", b"b")])
    with pytest.raises(ValueError, match="Duplicate"):
        decode_project(raw)


def test_uncompressed_limit():
    with pytest.raises(ValueError, match="size limit"):
        decode_project(NATIVE.read_bytes(), max_uncompressed_size=100)


def test_edit_api_errors():
    project = decode_project(NATIVE.read_bytes())
    with pytest.raises(KeyError):
        project.replace_entry("missing", b"x")
    with pytest.raises(ValueError, match="maintained"):
        project.replace_entry("program.sha256", b"x")
    with pytest.raises(ValueError, match="Unsupported"):
        encode_project(replace(project, header=b"oops"))


@pytest.mark.parametrize("replacement", [b"<position>-1</position>", b"<position>oops</position>"])
def test_invalid_position(replacement):
    xml = decode_project(NATIVE.read_bytes()).read("task/T1.rll")
    with pytest.raises(ValueError):
        decode_program(xml.replace(b"<position>0</position>", replacement, 1))
