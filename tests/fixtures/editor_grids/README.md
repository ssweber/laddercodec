# Editor grids

The grids are lists of cases for CLICK's instruction dialogs: an instruction, a mode and the
text to type in each field. ClickNick's runner (`click_runner.py try`) types each case into the
dialog, presses OK and records whether CLICK accepted it or refused it, with the error box's
code and message. The answers are what laddercodec's field rules are to be tightened to.

## Files

Each grid has a verdicts file beside it, `<grid>.verdicts.json`. The runner reads the grid only.

| Grid | What it holds |
| --- | --- |
| `preflight.json` | the first case of every row of the Math, Copy, Out and Search grids: each field and state in one short run |
| `risky.json` | the spellings a dialog field may not take as typed, for Math, Copy, Out and Search: empty, a space at either end, a tab, a character outside ASCII, text over 40 characters (128- and 129-character quoted text) |
| `preflight_compare.json`, `risky_compare.json` | the same for Compare |
| `preflight_fill.json`, `risky_fill.json` | the same for Fill |
| `preflight_<dialog>.json`, `risky_<dialog>.json` | the same for each of Timer, Counter, Shift, For, Drum and Send (`preflight_timer.json`, `risky_timer.json` and so on) |
| `math_decimal.json`, `math_hex.json` | Math (without the risky spellings): each bank and pointer form as the result, as an operand (with a constant and alone), as a RAND bound and as a SUM range; every constant spelling as an operand and alone; RAND with equal and reversed bounds; the range functions |
| `copy_single.json` | Single Copy: each bank, pointer form and constant spelling as the source and the destination; each source bank against each destination bank; constants against each bank; text into TXT; text with a quote inside it, into TXT1 and into a TXT pointer |
| `copy_block.json` | Block Copy: source ranges, destination banks, bank pairs |
| `copy_pack.json` | Pack: each bit bank against each register bank at 16 and 32 bits (and 1, 2, 17 and 33 for DS and DD); register sources |
| `copy_unpack.json` | Unpack: the same, in the other direction |
| `out.json` | Out: each bank, pointer form and constant as the target; ranges |
| `copy_fill.json` | Fill: each bank, pointer form and constant spelling as the value; each bank as the destination range, with a reversed range, one point and the bank's last address; each value bank against each destination bank; constants against each bank; text and numbers into TXT; text with a quote inside it; hex above FFFFh into each register bank; reals of 7 significant digits and more; ranges in SD |
| `compare.json` | Compare: each bank and pointer form as A and as B; every constant spelling as B, and a constant of each kind as A; each register bank against each register bank and against constants; each operator on numbers, on hex, on two texts, and on hex against a number or a number against text; text with a quote inside it, as A and as B |
| `search.json` | Search: each bank as the table, with its ends; each bank, pointer form and constant as the value; each bank as the result and as the found flag; each operator on numbers, hex and text; text with a quote inside it as the value; the Continuous and One Shot options |
| `timer.json` | Timer: each kind with each unit; Retentive on in each unit, and on an off-delay timer; the preset at 0, 32767, 32768 and -1 in each kind and unit; each constant spelling, bank and pointer form as the preset; each bank as the timer number; the current value typed |
| `counter.json` | Counter: each count type; the preset at 0, -1, 2147483647, 2147483648, -2147483648 and -2147483649 in each type, and at 12 and 13 characters; each constant spelling, bank and pointer form as the preset; each bank as the counter number, with the ends of CT; the current value typed |
| `shift.json` | Shift Register: C1..C8, X001..X008 and Y001..Y008; the ranges of C, X and Y, with a reversed range, one bit and an end past the bank, and one range of each other bank; each bank as the start and as the end |
| `for.json` | For: each constant spelling, bank and pointer form as the number of loops; One Shot on and off |
| `drum.json` | Drum, in Time Base and Event Base: each unit, and a unit on an event drum; a duration of 0, 32767, 32768, 39999, 40000 and -1 in each unit; each constant spelling, bank and pointer form as a duration; 0, 1, 16 and 17 steps and outputs; an output used twice, and the completion flag as an output; each bank as an output, the current step, the elapsed time, the completion flag and an event; jog, and the step number to jump to |
| `send.json` | Modbus Send: each port; each function code with a 984 start of each kind and with each bank as the source; with CLICK addressing, each bit bank against each bit bank and each register bank against each register bank, and one case for each slave address bank that laddercodec refuses for the code; each bank as the source and as a CLICK slave address; the count at its caps, past a bank's end, from X001, X005, Y001, X101 and X816, and from TXT; each spelling of a 984 and a hex slave address, with `h` alone and `1HH`; a hex start near FFFEh with a DD, DF, CTD or TXT source; the Slave ID on each port, with a DS address; the server port and IP address of CPU Port1; each bank in each status field, with only its first address in the success and error bits, and one C bit in two of them; Word Swap |
| `receive_click.json`, `receive_click_count1.json` | Modbus Receive with CLICK addressing: for each function code, each local bank against each remote bank, at the lowest address of each. The count is 1 for function codes 01 and 02, and 2 for 03 and 04. `receive_click_count1.json` holds the FC03 and FC04 cases into YD0, and into DH1 from XD0 or YD0, again with a count of 1 |
| `drum_events.json` | an event drum whose first event is typed as `X001`, `~X001`, `!X001`, `/X001`, `rise(X001)`, `NC X001` or `X001,X002` |
| `drum_events_names.json` | an event drum whose first event is `X001`, text that names no bank (`Q1`, `ABC`, `1`, `C1A`), or a bank name alone (`DS`, `X`) |
| `drum_events_shapes.json` | an event drum and a time and event drum whose first event is `X001`, an address with a space (` DS1`, `DS 1`), a range, an address after `-` or `NOT `, `$41`, `X99999999`, a pointer, or `Y001,`; and a time and event drum whose first event is `~X001`, `rise(X001)`, `Q1`, `X`, `DS` or `DS1` |
| `drum_events_padded.json`, `drum_events_padded2.json` | an event drum whose first event is `X001`, `C000001`, `X0000001`, `X00000100`, `SC0000000001` or `C0002001`; and again `X100`, `C000001` and `SC0000000001` |
| `coil_sc.json` | Set and Reset of each SC address that Out writes, and of SC49 and SC163 |
| `coil_sc_ranges.json` | Out, Set and Reset of the SC ranges SC50..SC60, SC50..SC53 and SC162..SC165, each of which holds a read-only SC between writable ends, and of SC50..SC51 and SC60..SC61 |
| `compare_const.json` | Compare with constants: two texts, two numbers, a text against a number, `"A"=="B"` against `"C"`, and `"A"` against TXT1 |
| `coil_sc_ranges2.json` | Set and Reset of a range whose two ends are one address (`C1..C1`, `Y001..Y001`, `SC50..SC50`), a reversed range, a range across two banks, and `C1..C2` |
| `ip_field.json` | a Send and a Receive on CPU Port1, with each of these IP addresses: an IP with a part above 255, with three or five parts, with leading zeros (`01.2.3.4`, `001.002.003.004`), with letters, with a negative part, with a blank part, with a dot at the end, with a space at either end, or with commas; a blank IP; and `192.168.1.1` |
| `ip_field_neg.json` | a Send and a Receive on CPU Port1, with each of these IP addresses: `1.2.3.-2`, `1.2.3.-0`, `1.2.3.-01`, `1.2.3.-256`, `-1.-1.3.4`, `-1.2..4`, `.2.3.4`, `1.2.3.` and `1...4`; and `1.2.3.4` |

ClickNick wrote `receive_click.json`, `receive_click_count1.json`, `drum_events.json`,
`drum_events_names.json`, `drum_events_shapes.json`, `drum_events_padded.json`,
`drum_events_padded2.json`, `coil_sc.json`, `coil_sc_ranges.json`, `compare_const.json`,
`coil_sc_ranges2.json`, `ip_field.json` and `ip_field_neg.json`.
The files hold ClickNick's text as it wrote it. The generator does not write them. It reads
them and writes their verdicts files. A Receive case types `slave_address`, `master_address`,
`count`, `receiving`, `success`, `error` and `exception`, and picks an item in the `function`
and `addressing` lists. It types no Slave ID and picks no port, except in `ip_field.json`
and `ip_field_neg.json`. A case there picks CPU Port1 and types the Slave ID, `server_port`
and `ip`, as a Send case does. A case that types no `ip` leaves the IP control blank. A Set or Reset case types
`address` and `address_end` as an Out case does. A time and event drum case types the fields
of a time drum and the events of an event drum.

A case is `{"row", "case", "instruction", "mode", "fields"}`, as the runner reads it. A Search
case may add `options`, which maps an option's control id to 1 (on) or 0 (off): `5021` is
Continuous Search and `5022` is One Shot. A case without options leaves both buttons as the
dialog opens them. Both open unchecked. `case` is unique in its file and stable: it is built
from the fields' text. `row` groups the cases that ask one question (`copy.single.source.banks`).
Out has no `mode`. A Compare or Search case has the operator as its `mode`. Cases are in a fixed
order.

A Fill case has the mode `fill`. Its fields have the names that the runner gives the Copy
dialog's fields: `source` is the value, and `destination` to `destination_end` is the range.

A Timer, Counter, Shift, For or Drum case names everything except a list's item by
laddercodec's names:

- `instruction` is `timer`, `counter`, `shift`, `for` or `drum`.
- `mode` is the kind: `on_delay` or `off_delay` for Timer, `count_up`, `count_down` or
  `count_up_down` for Counter, and `time_drum` or `event_drum` for Drum. Shift and For have no
  mode.
- `fields` are the fields of the laddercodec class: `done`, `accumulator` and `preset` for
  Timer and Counter, `start_bit` and `end_bit` for Shift, and `count` for For. A drum's
  `num_steps` and `num_outputs` are the numbers typed in Number of Steps and Number of
  Outputs. A drum's list fields are named by their index, one for each step or output:
  `outputs[0]` to `outputs[15]`, `presets[0]` to `presets[15]` for each step's duration, and
  `events[0]` to `events[15]` for each step's event. Its other fields are `current_step`,
  `accumulator` (the elapsed time in the step), `completion_flag` and `jump_step`.
- `choices` picks the item of a list by the text that the list shows. The only list is `unit`
  (`ms`, `sec`, `min`, `hour` or `day`), for Timer and Drum.
- `options` sets a check box or radio button by the name of the flag: `retained` for Timer,
  `oneshot` for For, and `jog_enabled` and `jump_enabled` for Drum. Before the first run, the
  ClickNick session maps each option name to the id of its button.

CLICK fills in a timer's or counter's current value when you type its number: TD1 for T1,
and CTD1 for CT1. So a case leaves `accumulator` out. The one case in each of the rows
`timer.accumulator` and `counter.accumulator` types it, to find out whether the dialog takes
it. The runner reads these two read-only fields back and never types them.

Each drum case starts from a drum that laddercodec accepts and changes one field, list or
option. A refusal then names the field that the case changed. A refusal of `num_steps` names
`presets` or `events`, and a refusal of `num_outputs` names `outputs`. When a case changes the
number of steps or outputs, it also fills each step or output that the new number adds.

Many of Send's fields and lists mirror those in the runner's entry for Receive. A Send case
names them like this:

- `instruction` is `send`. Send has no mode.
- The fields that mirror Receive's have Receive's names: `slave_id` (Slave ID),
  `slave_address` (Starting Slave Address), `master_address` (Starting Master Address),
  `count` (Number of Bits, or of Master Addresses), and `success`, `error` and `exception`
  (Exception Response).
- `sending` is the Sending bit, which has the name of `Send`'s field.
- `ip` and `server_port` are the IP Address and the Server Port Number. Only a case on a TCP
  port types them. `ip` is an IP address control, not an Edit. The runner fills it and reads it
  back from the control's four fields.
- `count` and `server_port` are Edits that take digits only. The runner sets their text
  directly, so it can still type other characters.
- The lists have Receive's names: `port` (Com Port), `function`, `addressing` and `word_swap`.
  A case picks an item by the text that the list shows. CLICK resets Word Swap to OFF when
  the fields are filled, so the runner picks the item again before it presses OK.

Each Send case starts from a Send that laddercodec accepts with the case's function code and
addressing, and changes one field or list. The plain Send writes DS1 to the holding register
400001 of slave 1 on CPU Port2, with function code 06, the status bits C100, C101 and C102,
and DS100 for the exception response. A case with function code 05 or 15 sends C1 instead. It
writes to coil 1 in 984 addressing and to C1 in CLICK addressing. In hex addressing, the Send
writes to 0h. A case picks an item in the port, function and addressing lists, so it does not
depend on what the dialog opens with. A case with function code 05 or 06 leaves the count out,
in case the dialog closes the field for one element. The row `send.count.single` types it. A
case label names the function code, the addressing (`984`, `hex` or `click`), the slave
address, the master address and the count, and then each other field or list that differs
from that Send. A refusal can name a field that the case did not change, because laddercodec
checks the fields in its own order. For example, a 984 start of a kind that the function code
does not write is refused on the source.

Compare is a contact, so the runner runs its cases only with `--wire`. Compare's preflight and
risky cases are in `preflight_compare.json` and `risky_compare.json`. Run those with `--wire`
too. The runner refuses `--wire` for Counter, Shift Register, Drum, For and a retentive
Timer, because it wires only the first input and CLICK reports C0202 for an unwired reset.

When a field does not read back as typed, the runner records the case as `not_taken` and closes
the dialog with Cancel. A Compare or Search case with text and one of `>`, `<`, `>=` or `<=`
comes back `not_taken`, because CLICK closes the field for entry. Then the runner goes on to
the next case. **Run the preflight and risky files first.** Preflight tries one case in each
row. A field that cannot take text (Out's range end, a constant or pointer in a range end) then
shows up in a short run. The risky spellings are in
files of their own. The other files hold only spellings that the generator expects a field to
read back as typed. Preflight repeats cases of the other files, with the same labels.

The runner takes about 4 seconds a case. The files are split by dialog and mode so none passes
about 2,000 cases. The generator prints the number of cases and the time of each file.

## Regenerating

```bash
make editor-grids                         # write these files, then check them
uv run devtools/editor_grids.py --check   # exit 1 if they differ, messages included
```

The generator builds the lists from laddercodec's own bank ranges, X/Y slots, pointer banks and
constant kinds, so a new bank or kind changes the grids. `tests/test_editor_grids.py` fails when
the committed files differ from what the generator writes. The Fill, Compare, Search, Timer,
Counter, For and Drum grids use the constant spellings of the other grids. They add `0ffh` to
the hex spellings. The Timer, Counter, For and Drum grids also try values of their own, such as
-1 for a timer preset and 39999 for a drum duration.

CLICK has answered the Math, Copy, Out, Compare and Search grids. If you change a list that they
use, their cases change, and `tests/test_editor_answers.py` fails because the answers no longer
match the grid. The generator adds the Search cases to `preflight.json` and `risky.json` after
the others. The test compares the cases of all these dialogs in those two files.

## Verdicts

`<grid>.verdicts.json` maps each case's label to what laddercodec's rules say today:
`{"verdict": "accepted"}`, or `{"verdict": "refused", "error", "field", "message"}`. A case is
built as the instruction laddercodec would make from it: Block Copy's destination end is the
start plus the source's length, which CLICK works out itself; a Copy or Block Copy of TXT
into a number register other than DF takes Copy Character Value (`to_value`), the dialog's
default, since a plain copy is refused; a single Copy of a number constant or a number
register into TXT takes the dialog's default too, Copy Value as text with Suppress zero for
an integer and Real Numbering for a real; Pack and Unpack take the bits or
words form of the bank typed. A Fill case is built as `Fill`, with `source` as the value,
`destination` to `destination_end` as the range and no option set. A Compare case is built as
`CompareContact` with A as `left` and B as `right`. A Search case sets `continuous` when its
options set 5021 to 1, and `oneshot` when they set 5022 to 1.

A Timer or Counter case without `accumulator` is built with the current value that CLICK
assigns: the TD or CTD register with the number of the timer or counter. If that number is
not a T or CT address, the case is built with TD1 or CTD1, so that only the number is
refused. A `count_up_down` case is built as `count_up` with a down input. A Drum case is built
with the number of steps and outputs that `num_steps` and `num_outputs` hold. A field that the
case leaves out is blank. No cell of the pattern is set. A case's `unit` item is built as the
laddercodec unit that it names: `ms` as `Tms`, `sec` as `Ts`, `min` as `Tm`, `hour` as `Th`
and `day` as `Td`. An option that a case sets to 1 is on, and any other option is off.

A Send case is built as `Send` with the function code that the case picks. The port picks the
target: `CPU Port1` and `WLAN Port` build a `ModbusTcpTarget`, and any other port builds a
`ModbusRtuTarget`. The slave address is the `remote_start`. With CLICK addressing it is the
address text. With 984 addressing it is a `ModbusAddress` of the text. With hex addressing it
is a `ModbusAddress` of the text whose register type is `coil` for function code 05 or 15 and
`holding` for 06 or 16. A Slave ID, count or server port of decimal digits, with or without a
minus sign, is built as that number. Any other text is passed as it is, so laddercodec refuses
it as not a number, or reads a Slave ID as a DS address. A case without `count` is built with
a count of 1. Word Swap is on when the case picks `ON`.

A Receive case is built as `Receive` with the function code that the case picks, from slave 1
on CPU Port2. If the case picks a port, the Receive is on that port. If the case types a Slave
ID, the Receive reads from that Slave ID. On `CPU Port1` or `WLAN Port`, the target is a
`ModbusTcpTarget` with the case's IP and server port, as for a Send. A Send or Receive case
that types no IP is built with the IP `""`. With CLICK addressing, the slave address is the address text. With
any other addressing, or with none picked, it is a `ModbusAddress` of the text. A case
without `count` is built with a count of 1.

laddercodec reads a slave address that ends in `h` as hex, and an address of digits only as
MODBUS 984. It would read `1h` typed in 984 addressing as hex, and `10` typed in hex addressing
as a 984 address. The grid leaves out both cases.

The grid learns only whether CLICK's dialog accepts each case. It does not learn which X point
a Send from X001 sends as its 17th element, which needs a PLC. It does not learn what CLICK
stores for a slave address typed with `h`, which needs a saved project.

The verdicts exist to be compared with CLICK's answers case by case. `--check` and the test
both compare each whole verdict, its message included.

## CLICK's answers

An answers file has one entry per case under `cases`: the case's own keys, then `outcome`
(`accepted`, `refused`, `not_taken`, `crashed` or null), `code` and `message` (the error box's), `syntax_check`,
`seconds`, `read_back` (each field as the dialog showed it), `limits` (each field's text limit)
and, for an accepted case that was saved, `stored` (the saved rung as laddercodec CSV rows).
Where one OK raised a chain of error boxes, `boxes` lists each box's code and message, and
`code` and `message` are the first box's. The answers sit beside the grids:

| File | What it holds |
| --- | --- |
| `preflight.answers.json`, `risky.answers.json` | the answers to the files of those names (112 and 80 cases, Search cases included) |
| `compare.answers.json`, `search.answers.json` | the answers to the files of those names (677 and 813 cases) |
| `preflight_compare.answers.json`, `risky_compare.answers.json` | the answers to the files of those names (13 and 11 cases) |
| `out.answers.json`, `copy_single.answers.json`, `copy_block.answers.json`, `copy_pack.answers.json`, `copy_unpack.answers.json`, `math_decimal.answers.json`, `math_hex.answers.json` | the answers to the files of those names (477, 908, 661, 615, 603, 1,071 and 883 cases); six Pack cases (33 T, CT or SC bits into DS or DD) hold `boxes`: OBJ-041, then OBJ-024 |
| `timer.answers.json`, `counter.answers.json`, `shift.answers.json`, `for.answers.json`, `copy_fill.answers.json`, `drum.answers.json`, `send.answers.json` | the answers to the files of those names (388, 355, 231, 249, 973, 754 and 981 cases). A Timer's `read_back` also holds `accumulator`, and a Counter's holds `accumulator` and `completion_bit`. CLICK fills these from the done bit. A `not_taken` case may have a null `read_back` and null `limits` |
| `risky_timer.answers.json`, `risky_shift.answers.json`, `risky_for.answers.json`, `risky_drum.answers.json`, `risky_send.answers.json`, `risky_counter.answers.json`, `risky_fill.answers.json` | the answers to the files of those names (11, 4, 9, 15, 56, 11 and 14 cases). Two Counter cases and one Fill case are `crashed`. A `not_taken` or `crashed` case may have a null `read_back` and null `limits` |
| `receive.answers.json` | 18 Receive cases: a master address in each bank, with function code 01 and 03 (the cases are in the file) |
| `receive_count.answers.json` | 10 Receive cases that set the count (function code 03): a TXT master at count unset, 1, 2, 3, 4, 126, 250 and 252, and a DS master at 1 and 2 (two runs). `read_back` holds every field, the count and Slave ID too; for the unset case the count is the 2 the dialog held |
| `receive_click.answers.json` | the answers to `receive_click.json` and then to `receive_click_count1.json` (512 and 36 cases, two runs). `read_back` holds the Slave ID too. The 32 cases into YD0 with a count of 2 are `not_taken`, because the dialog held the count at 1 |
| `drum_events.answers.json` | the answers to `drum_events.json` (7 cases) |
| `drum_events_names.answers.json` | the answers to `drum_events_names.json` (7 cases) |
| `drum_events_shapes.answers.json` | the answers to `drum_events_shapes.json` (28 cases) |
| `drum_events_padded.answers.json` | the answers to `drum_events_padded.json` and then to `drum_events_padded2.json` (6 and 3 cases, two runs) |
| `coil_sc.answers.json` | the answers to `coil_sc.json` (54 cases) |
| `coil_sc_ranges.answers.json` | the answers to `coil_sc_ranges.json` (15 cases) |
| `compare_const.answers.json` | the answers to `compare_const.json` (7 cases) |
| `coil_sc_ranges2.answers.json` | the answers to `coil_sc_ranges2.json` (16 cases) |
| `ip_field.answers.json` | the answers to `ip_field.json` (30 cases), with the IP typed into the IP control. The runner types only four numbers from 0 to 255 there, so each other IP that a case types is `not_taken`. The four cases with leading zeros are `not_taken` too, because the control reads them back without the zeros |
| `ip_field_per_field.answers.json` | the answers to `ip_field.json` again (30 cases), with each part of the IP set as text. No one can type some of this text into the IP control |
| `ip_field_neg.answers.json` | the answers to `ip_field_neg.json` (20 cases), with each part of the IP set as text, as in `ip_field_per_field.answers.json` |
| `pickcheck.answers.json` | 28 cases that check the Address Picker's lists against the dialog |
| `picker_lists.answers.json` | 15 cases from the Address Picker's lists for a hex Math result, Pack's destination and Unpack's destination: an address the list holds is accepted, an SC or SD (or another bank) it leaves out is refused |
| `rule_rows.answers.json` | 3 cases CLICK accepts: a Block Copy of TXT1..TXT2 into TXT11, and a hex Math into YD0 and YD1 (`DH1 + DH2`) |
| `sc_sd_writable.answers.json` | the SC and SD addresses the Address Picker lists, per instruction, field and bank, with the bank tabs it leaves open; 12 fields, 8 of them for a field the picker lists only after another field is filled (`filled`: the source of a Pack or Unpack), and a bank with no list is null |
| `coil_sc_picker.answers.json` | the same lists for the address and range end of Set and of Reset, laid out as `sc_sd_writable.answers.json` (4 fields) |

They are CLICK's, and are never edited to fit the code: when a rule and an answer disagree, the
rule changes. The `plc`, `runs` and `clip` fields name no machine. The IP addresses in the Send
cases are the text that the cases type. Every case and every answer is as the runner wrote it.

A case with `outcome` `not_taken` has no answer, because CLICK did not take the text. The rules
must refuse it. A case with a null `outcome` has none either: CLICK closed before it answered. A case with
`outcome` `crashed` has none: CLICK exited after the case's OK without answering. The `read_back`
of a `not_taken` case shows what the dialog held. It differs from the text that the case asked
for in four ways only. A Drum's dialog holds a step or output count past its bound at the bound,
so 0 is held as 1 and 17 as 16. A Receive's dialog holds the count of a YD master address at 1.
A dialog that closes the count box holds no count. The IP control holds each part of an IP
without its leading zeros, and it holds no IP where the runner did not type one. 27
`not_taken` cases have a null `read_back` and null `limits`, because the runner never reached
their fields. They are the Send cases on a slot port that the PLC's port list does not hold,
two Send cases whose Word Swap list is closed, and a unit on an event drum.

`tests/test_editor_answers.py` compares them with laddercodec's rules: each case is rebuilt with
the generator's builders (a Receive at the count that the case types, else at the count that
the dialog held where an answer records one, else 1) and its outcome compared with CLICK's, then the
refusal's `click_id` with CLICK's code (only where the rules give a `click_id`; most refusals have
none yet, and the test records how many codes it compared), then the saved rows of an accepted case
with what `read_csv` makes of them (a `raw(...)` is a difference), then the writable lists with the SC and
SD addresses the rules accept (a field's list holds with the other fields as `filled` gives them; a bank with
no list means the rules accept no address of it). A case with more text than its field's `limits` is skipped: the
runner sets text by WM_SETTEXT, which ignores the limit, so no user can type it. Each difference
is listed in the test with its reason and its roadmap item; the test fails on one that is not
listed and on a listed one that is gone.
