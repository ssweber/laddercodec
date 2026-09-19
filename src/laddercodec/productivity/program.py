"""Read the observed JAXB ladder XML representation without guessing opcodes."""

from xml.dom import Node, minidom

from .model import Element, Instruction, Program, Rung, TagReference

_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _children(node: minidom.Element, name: str) -> list[minidom.Element]:
    return [
        child
        for child in node.childNodes
        if isinstance(child, minidom.Element) and child.tagName == name
    ]


def _text(node: minidom.Element, name: str) -> str:
    children = _children(node, name)
    if len(children) != 1:
        raise ValueError(f"Expected one {name} element in {node.tagName}")
    return "".join(
        child.data for child in children[0].childNodes if isinstance(child, minidom.Text)
    )


def _integer(node: minidom.Element, name: str) -> int:
    value = int(_text(node, name))
    if value < 0:
        raise ValueError(f"Negative {name} in {node.tagName}")
    return value


def _standalone_xml(node: minidom.Element) -> bytes:
    """Retain in-scope namespaces, including prefixes used only in xsi:type."""
    copy = node.cloneNode(deep=True)
    assert isinstance(copy, minidom.Element)
    parent: Node | None = node
    while isinstance(parent, minidom.Element):
        for name in parent.attributes.keys():
            if (name == "xmlns" or name.startswith("xmlns:")) and not copy.hasAttribute(name):
                copy.setAttribute(name, parent.getAttribute(name))
        parent = parent.parentNode
    return copy.toxml(encoding="utf-8")


def _instruction(node: minidom.Element) -> Instruction:
    kind = node.getAttributeNS(_XSI, "type")
    if not kind:
        raise ValueError("Instruction has no xsi:type")
    tags = tuple(
        TagReference(_text(tag, "name"), _text(tag, "ID"), _integer(tag, "type"))
        for tag in node.getElementsByTagName("data")
        if tag.getAttributeNS(_XSI, "type").split(":")[-1] == "tagStub"
    )
    return Instruction(kind, _standalone_xml(node), tags)


def decode_program(data: bytes) -> Program:
    """Read task/*.rll XML, preserving unknown instruction XML and original bytes.

    This is an inspection model, not an execution model or a complete schema
    validator. Wire subtypes and instruction properties remain vendor values.
    """
    document = minidom.parseString(data)
    try:
        root = document.documentElement
        if root is None:
            raise ValueError("Missing Program XML root")
        if root.tagName != "Program":
            raise ValueError(f"Expected Program XML, got {root.tagName}")
        rungs = []
        for row in _children(root, "rungs"):
            elements = []
            for element in _children(row, "elements"):
                instructions = _children(element, "instruction")
                if len(instructions) > 1:
                    raise ValueError("Multiple instructions in one element")
                elements.append(
                    Element(
                        _integer(element, "position"),
                        _integer(element, "repeat"),
                        _integer(element, "elementType"),
                        _integer(element, "subType"),
                        _instruction(instructions[0]) if instructions else None,
                    )
                )
            disabled = _text(row, "disabled")
            if disabled not in ("true", "false", "1", "0"):
                raise ValueError(f"Invalid disabled value: {disabled}")
            rungs.append(
                Rung(
                    _integer(row, "rungNumber"),
                    _integer(row, "subRungNumber"),
                    _text(row, "comment"),
                    disabled in ("true", "1"),
                    tuple(elements),
                )
            )
        return Program(tuple(rungs), data)
    finally:
        document.unlink()
