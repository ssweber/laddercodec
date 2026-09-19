"""Exploratory Java serialization reader; parses data without loading Java classes.

Supports the tokens encountered in this clipboard capture, not all Java streams.
"""

import json
import struct
import sys
from pathlib import Path


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.handles = {}

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError(f"Truncated stream at {self.pos}")
        b = self.data[self.pos : self.pos + n]
        self.pos += n
        return b

    def num(self, fmt):
        return struct.unpack(">" + fmt, self.take(struct.calcsize(">" + fmt)))[0]

    def utf(self, n=None):
        if n is None:
            n = self.num("H")
        text = self.take(n).replace(b"\xc0\x80", b"\x00").decode("utf-8", "surrogatepass")
        return text.encode("utf-16", "surrogatepass").decode("utf-16")

    def add(self, value):
        handle = 0x7E0000 + len(self.handles)
        self.handles[handle] = value
        if isinstance(value, dict):
            value["$id"] = handle
        return value

    def resolve(self, value):
        if isinstance(value, dict) and "$ref" in value:
            return self.handles[value["$ref"]]
        return value

    def annotations(self):
        values = []
        while self.data[self.pos] != 0x78:
            values.append(self.read())
        self.take(1)
        return values

    def primitive(self, kind):
        fmt = {"B": "b", "C": "H", "D": "d", "F": "f", "I": "i", "J": "q", "S": "h", "Z": "?"}
        return self.num(fmt[kind])

    def read(self):
        offset = self.pos
        token = self.num("B")
        if token == 0x70:
            return None
        if token == 0x71:
            handle = self.num("I")
            assert handle in self.handles, (offset, handle)
            return {"$ref": handle}
        if token in (0x74, 0x7C):
            return self.add(self.utf(self.num("H" if token == 0x74 else "Q")))
        if token == 0x72:
            name, uid = self.utf(), self.num("q")
            desc = self.add({"kind": "class", "name": name, "serialVersionUID": uid})
            desc["flags"] = self.num("B")
            fields = []
            for _ in range(self.num("H")):
                kind, name = chr(self.num("B")), self.utf()
                field = {"type": kind, "name": name}
                if kind in ("L", "["):
                    field["signature"] = self.resolve(self.read())
                fields.append(field)
            desc["fields"] = fields
            desc["annotations"] = self.annotations()
            desc["super"] = self.read()
            return desc
        if token == 0x73:
            desc = self.resolve(self.read())
            obj = self.add({"kind": "object", "class": desc["name"], "fields": {}})
            chain = []
            while desc:
                chain.append(desc)
                desc = self.resolve(desc["super"])
            for desc in reversed(chain):
                flags = desc["flags"]
                if flags & 4:
                    raise ValueError("Externalizable class not supported")
                for field in desc["fields"]:
                    kind = field["type"]
                    obj["fields"][desc["name"] + "." + field["name"]] = (
                        self.read() if kind in ("L", "[") else self.primitive(kind)
                    )
                if flags & 1:
                    obj.setdefault("annotations", {})[desc["name"]] = self.annotations()
            return obj
        if token == 0x75:
            desc = self.resolve(self.read())
            arr = self.add({"kind": "array", "class": desc["name"]})
            n = self.num("i")
            if not 0 <= n <= 1000000:
                raise ValueError(f"Unexpected array length {n}")
            kind = desc["name"][1]
            arr["values"] = [
                self.read() if kind in ("L", "[") else self.primitive(kind) for _ in range(n)
            ]
            return arr
        if token == 0x7E:
            desc = self.resolve(self.read())
            enum = self.add({"kind": "enum", "class": desc["name"]})
            enum["value"] = self.resolve(self.read())
            return enum
        if token in (0x77, 0x7A):
            return {
                "kind": "block",
                "hex": self.take(self.num("B" if token == 0x77 else "I")).hex(),
            }
        raise ValueError(f"Unsupported token {token:#x} at {offset:#x}")


if __name__ == "__main__":
    path = Path(sys.argv[1])
    reader = Reader(path.read_bytes())
    assert reader.take(4) == bytes.fromhex("aced0005")
    root = reader.read()
    assert reader.pos == len(reader.data), (reader.pos, len(reader.data))
    report = {"bytes_consumed": reader.pos, "root": root, "handles": reader.handles}
    output = path.with_suffix(".json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Parsed all {reader.pos} bytes; {len(reader.handles)} handles; {output}")
    for obj in reader.handles.values():
        if isinstance(obj, dict) and obj.get("kind") == "class":
            print(obj["name"], [(f["type"], f["name"]) for f in obj["fields"]])
