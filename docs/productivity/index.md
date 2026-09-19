# Productivity projects (experimental)

```python
from pathlib import Path

from laddercodec.productivity import decode_program, decode_project, encode_project

source = Path("example.adpro").read_bytes()
project = decode_project(source)
assert encode_project(project) == source

for name in project.program_names:
    program = decode_program(project.read(name))
    for row in program.rungs:
        for cell in row.elements:
            if cell.instruction:
                print(row.number, row.subrung, cell.position, cell.instruction.kind)
```

This namespace reads two observed ADPRO variants, verifies archive CRCs and the
newer content checksum, and exposes ladder XML records. It has no runtime
dependencies. Top-level `laddercodec.encode` and `decode` remain CLICK APIs.

The native fixtures cover one two-button latch example saved in versions 3.12.1
and 4.7.2.4. This is experimental format support, not a claim of complete
Productivity instruction coverage. Reopening edited/generated archives in
Productivity has not yet been verified.

## Edit an existing XML entry

```python
document = project.xml("task/T1.rll")
comment = document.getElementsByTagName("comment")[0]
while comment.firstChild is not None:
    comment.removeChild(comment.firstChild)
comment.appendChild(document.createTextNode("Edited rung comment"))

updated = project.replace_xml("task/T1.rll", document)
Path("example-edited.adpro").write_bytes(encode_project(updated))
```

`Project` is immutable. `xml()` returns an independent DOM; `replace_xml()` or
`replace_entry()` explicitly applies a change. The writer updates
`program.sha256` when present. Other entry contents, including opaque binary
entries, retain their original bytes; ZIP metadata is carried forward.
Changed archives are recompressed. Only unchanged archives have a byte-identical
container guarantee.

Use the DOM when editing XML: namespace declarations can be required by values
such as `xsi:type="xs:int"`, even if no element or attribute name uses `xs`.
Instruction inspection records retain self-contained XML with inherited
namespace declarations. Editing a `Program` inspection view does not edit its
source archive. There is no instruction-specific encoder yet.

## Observed container

| Saved version | Header | Entries | Content checksum |
| --- | --- | ---: | --- |
| 3.12.1 (21) | `AD C0 30 00` | 11 | Absent |
| 4.7.2 (4) | `AD C0 30 02` | 13 | `program.sha256`, 32 binary bytes |

Both headers are followed by a normal ZIP local header at offset 4. Python's
`ZipFile` handles the prefix directly. Unknown header variants are rejected.

| Entry | Meaning |
| --- | --- |
| `task/T1.rll` | Ladder rows, instructions, wiring, comments |
| `program.tag` | Tag database |
| `program.prj` | Project/task settings |
| `program.cfg` | Hardware configuration |
| `program.pld` | Software/project versions and save timestamp |
| `program.act` | Account data; opaque in the current save |
| `program.udi` | Opaque bytes in the current save |

The checksum matches SHA-256 over the concatenation of all uncompressed entry
contents except `program.sha256`. No filenames or separators are included.
Both sample entry lists are sorted; these captures cannot distinguish archive
order from explicit filename sorting. The writer retains entry order and does
not provide add/remove/rename operations. Entry replacement alone does not
validate vendor semantics such as tag IDs, symbols, or required instruction
properties. Treat the checksum as container integrity, not proof of a valid PLC
program.

## Ladder records and clipboard agreement

Each `rungs` record has a rung number and subrung number. A logical rung can
occupy multiple rows. Element records contain `position`, `repeat`,
`elementType`, and `subType`; `repeat` counts additional consecutive cells.
Position 6, repeat 13 covers positions 6 through 19 inclusive.

Observed `elementType=0` cells contain instructions; type 1 cells contain wire
codes. Wire subtype connectivity is not yet mapped. Instruction names such as
`adcInstNO`, `adcInstNC`, `adcInstOUT`, and `adcInstSTMR` appear in `xsi:type`.
Tag references include readable names and IDs such as `C-000001`.

The clipboard stores Java serialization (`AC ED 00 05`). The captured 6,709-byte
stream includes two subrungs, comments, instruction objects, tag objects, and a
timer preset. The data-only research parser consumes all bytes and resolves 180
handles without loading Java classes. It supports this stream, not all possible
Java serialization features. There is no public clipboard encoder/decoder yet.

Regression tests compare the native clipboard to both versions' XML: all 29
occupied positions, element types, wire subtypes, instruction kinds, and comments
match. This does not establish complete operand or execution equivalence.

The Windows clipboard format names observed were:

```text
JAVA_DATAFLAVOR:application/x-java-serialized-object; class=com.adc.common.datatransfer.n
JAVA_DATAFLAVOR:application/x-java-serialized-object; class=com.adc.common.datatransfer.i
```

Both contained identical bytes. Their numeric format IDs are session-specific;
the obfuscated class names may also change between releases.

## Bulk instruction discovery

`devtools/productivity/java/InspectProductivity.java` inspects an installed
`productivity.jar`. Its inventory mode reads class metadata without constructing
instruction objects. It records inherited public getters, corresponding setters,
JAXB annotations, constructors, and enum names.

On 4.7.2.4 it inspected **163 instruction classes with zero errors**. The full
generated report goes in ignored `build/`; a compact inventory and native capture
provenance are preserved with the fixtures. The metadata describes Java/XML
structure, not instruction behavior or complete validation rules.

The serialization mode constructs one default instruction and marshals it using
the installed JAXB package registries. A standalone STMR serialization succeeded
with the vendor's Java 17 runtime. Its default time base is `centiSecond`; the
native fixture explicitly uses `second`. This demonstrates access to the vendor
serializer, not successful project generation. Unassigned operands are omitted.

The probe requires a local JDK compiler and the installed Productivity runtime
and libraries. It uses reflection, so compiling the helper does not require
vendor classes. No vendor JARs or native DLLs are copied into this repository.
Serialization initializes vendor classes; the launcher supplies required
simulator paths and routes child-process app-data/temp paths under `build/`.

Create a local argument file, one argument per line (paths with spaces need no
quotes inside this file):

```text
--javac
C:/path/to/jdk/bin/javac.exe
--java
C:/path/to/Productivity-JVM/bin/java.exe
--suite
C:/Program Files/AutomationDirect/Productivity Suite 4.7.2.4
--output
build/productivity/inventory.json
```

Run it through the development target:

```console
make productivity-java ARGS=@build/productivity-java-args.txt
```

For the default timer experiment, change the output path to an XML file and add:

```text
--class-name
com.adc.common.model.instruction.AdcInst_STMR
```

Other inspection targets:

```console
make productivity-inspect ARGS=tests/fixtures/productivity/two-button-latch/project-4.7.2.4.adpro
make productivity-clipboard ARGS=tests/fixtures/productivity/two-button-latch/rung-4.7.2.4.clipboard.bin
make productivity-capture
make productivity-example
```

Clipboard capture reads the existing clipboard without clearing or replacing it.
Capture files go under `build/productivity/captures/` by default.

`productivity-example` writes `build/productivity/two-button-latch-7s.adpro`
with the sample timer preset changed from 3 to 7 seconds. It preserves the
original comments, which still describe three seconds, and does not open or
transfer the project. This isolated copy is for the pending application-open
check.

## Next checks

1. Open an isolated edited project in Productivity and compare its next save.
2. Capture a `.adtkl` Task Library group, a documented task import route in
   installed help topic P304; system IDs are reassigned during library import.
3. Use targeted bytecode inspection to map wire connectivity and serializer
   adapters, then add representative branching/instruction fixtures.
4. Extend the Java harness to populate operands and compare against native XML
   before designing typed instruction writers.

The installed Castor mapping XML is a semantic reference, but its element names
differ from the observed JAXB XML. It is not an authoritative schema for these
captures. No loose ladder files were found in the inspected temporary paths;
the `adcsim*` directories contained simulator/browser storage.
