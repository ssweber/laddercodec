"""Build an isolated seven-second timer copy from the captured native project."""

from pathlib import Path

from laddercodec.productivity import decode_project, encode_project


def main() -> None:
    source = Path("tests/fixtures/productivity/two-button-latch/project-4.7.2.4.adpro")
    project = decode_project(source.read_bytes())
    document = project.xml("task/T1.rll")
    timers = [
        item
        for item in document.getElementsByTagName("instruction")
        if item.getAttributeNS("http://www.w3.org/2001/XMLSchema-instance", "type") == "adcInstSTMR"
    ]
    if len(timers) != 1:
        raise ValueError("Expected exactly one timer in the captured example")
    preset = timers[0].getElementsByTagName("presetValue")[0]
    for name in ("constText", "value"):
        element = preset.getElementsByTagName(name)[0]
        for child in list(element.childNodes):
            element.removeChild(child)
        element.appendChild(document.createTextNode("7"))
    encoded = encode_project(project.replace_xml("task/T1.rll", document))
    decode_project(encoded)
    destination = Path("build/productivity/two-button-latch-7s.adpro")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    print(f"Wrote {destination}; archive/checksum verified; application-open verification pending.")
    print("Only the timer preset was changed; original rung comments still describe three seconds.")


if __name__ == "__main__":
    main()
