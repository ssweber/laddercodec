"""Preserve observed ADPRO containers and update their content checksum."""

from copy import copy
from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import BytesIO
from xml.dom import minidom
from zipfile import BadZipFile, ZipFile, ZipInfo

_LEGACY_HEADER = bytes.fromhex("adc03000")
_HASHED_HEADER = bytes.fromhex("adc03002")
_CHECKSUM = "program.sha256"
_MAX_UNCOMPRESSED_SIZE = 256 * 1024 * 1024


@dataclass(frozen=True)
class ProjectEntry:
    name: str
    data: bytes


def _digest(entries: tuple[ProjectEntry, ...]) -> bytes:
    digest = sha256()
    for entry in entries:
        if entry.name != _CHECKSUM and not entry.name.endswith("/"):
            digest.update(entry.data)
    return digest.digest()


@dataclass(frozen=True)
class Project:
    """An immutable archive with opaque entries preserved as bytes.

    Use replace_entry/replace_xml to edit existing entries. Inspection models
    returned by decode_program do not mutate this archive.
    """

    header: bytes
    entries: tuple[ProjectEntry, ...]
    comment: bytes = b""
    _source: bytes | None = field(default=None, repr=False, compare=False)
    _original: tuple[bytes, tuple[ProjectEntry, ...], bytes] | None = field(
        default=None, repr=False, compare=False
    )

    def read(self, name: str) -> bytes:
        for entry in self.entries:
            if entry.name == name:
                return entry.data
        raise KeyError(name)

    @property
    def program_names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries if entry.name.endswith(".rll"))

    def xml(self, name: str) -> minidom.Document:
        """Return an independent editable DOM, preserving namespace declarations."""
        return minidom.parseString(self.read(name))

    def replace_entry(self, name: str, data: bytes) -> "Project":
        """Replace an existing entry; encode_project recalculates the checksum."""
        self.read(name)
        if name == _CHECKSUM:
            raise ValueError("program.sha256 is maintained by encode_project")
        return replace(
            self,
            entries=tuple(
                ProjectEntry(name, data) if entry.name == name else entry for entry in self.entries
            ),
        )

    def replace_xml(self, name: str, document: minidom.Document) -> "Project":
        """Serialize an edited DOM; unrelated entries retain their original bytes."""
        return self.replace_entry(name, document.toxml(encoding="utf-8"))


def _validate(header: bytes, entries: tuple[ProjectEntry, ...]) -> None:
    if header not in (_LEGACY_HEADER, _HASHED_HEADER):
        raise ValueError(f"Unsupported Productivity project header: {header.hex()}")
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate Productivity archive entry names")
    if (header == _HASHED_HEADER) != (_CHECKSUM in names):
        raise ValueError("Project header and program.sha256 presence disagree")


def decode_project(data: bytes, *, max_uncompressed_size: int = _MAX_UNCOMPRESSED_SIZE) -> Project:
    """Read the two observed ADPRO variants and verify ZIP CRCs and content SHA-256.

    No filesystem extraction occurs. The configurable size limit applies to the
    sum of archive entries. Unsupported headers and invalid checksums fail closed.
    """
    header = data[:4]
    if header not in (_LEGACY_HEADER, _HASHED_HEADER):
        raise ValueError(f"Unsupported Productivity project header: {header.hex()}")
    if data[4:8] != b"PK\x03\x04":
        raise ValueError("Expected ZIP local header at offset 4")
    with ZipFile(BytesIO(data)) as archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > max_uncompressed_size:
            raise ValueError("Productivity project exceeds uncompressed size limit")
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError("Duplicate Productivity archive entry names")
        entries = tuple(ProjectEntry(info.filename, archive.read(info)) for info in infos)
        comment = archive.comment
    _validate(header, entries)
    if header == _HASHED_HEADER:
        stored = next(entry.data for entry in entries if entry.name == _CHECKSUM)
        if stored != _digest(entries):
            raise ValueError("Productivity project SHA-256 mismatch")
    return Project(header, entries, comment, data, (header, entries, comment))


def encode_project(project: Project) -> bytes:
    """Write a supported archive, preserving opaque contents and ZIP metadata.

    Unchanged decoded projects return the exact original bytes. Edited projects
    are recompressed and their SHA-256 is updated. Acceptance of edited projects
    by the Productivity application has not yet been verified.
    """
    _validate(project.header, project.entries)
    if project._source is not None and project._original == (
        project.header,
        project.entries,
        project.comment,
    ):
        return project._source
    metadata: dict[str, ZipInfo] = {}
    if project._source is not None:
        try:
            with ZipFile(BytesIO(project._source)) as source:
                metadata = {info.filename: copy(info) for info in source.infolist()}
        except BadZipFile as exc:
            raise ValueError("Invalid source archive metadata") from exc
    stream = BytesIO()
    stream.write(project.header)
    with ZipFile(stream, "w") as archive:
        archive.comment = project.comment
        digest = _digest(project.entries)
        for entry in project.entries:
            info = metadata.get(entry.name, ZipInfo(entry.name))
            archive.writestr(info, digest if entry.name == _CHECKSUM else entry.data)
    return stream.getvalue()
