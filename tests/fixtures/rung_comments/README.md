# Rung comments outside ASCII

Each file holds one rung from CLICK 4.00: a contact on X001 and `out(Y001)`, with a comment.
The comment was put into CLICK in one of two ways:

- **Typed:** the text was set in CLICK's comment editor as UTF-16, and OK was pressed.
- **Pasted:** a clipboard with laddercodec's form of the comment was pasted into CLICK.

A `.bin` file is the clipboard after CLICK copied the rung. A `.scr` file is the `Scr1.tmp`
that CLICK saved for the same project. CLICK keeps the comment's RTF byte for byte through a
copy, a save and a reopen. In each `.bin`, these bytes are zeroed, because they hold the
project path or stale memory: 0x000C to 0x0214, the bytes after the NUL that ends the CPU
name, and every byte after the last data row of the grid. `decode()` reads the same rung from
the zeroed file as from the capture.

| File | Comment | How | RTF after `\pard` |
|---|---|---|---|
| `temperature.bin` | `Température 50°C` | typed | `\fs20 Temp\'e9rature 50\'b0C` |
| `euro.bin` | `€ µ ß` | typed | `\fs20\'80 \'b5 \'df` |
| `euro.scr` | `€ µ ß` | typed | the same as `euro.bin` |
| `arrow.bin` | `a → b` | typed | `\fs20 a 薔? b` |
| `simsun.bin` | `中` | typed | `\f0\fs20\'d6\'d0\f1 `, with font 0 SimSun, `\fcharset134` |
| `simsun.scr` | `中` | typed | the same as `simsun.bin` |
| `emoji.bin` | U+1F600 | typed | `\fs20唵7?嚃2?` |
| `emoji.scr` | U+1F600 | typed | the same as `emoji.bin` |
| `cjk_u.bin` | `中` | pasted as ` 3?`, then OK pressed in the editor | `\fs20 3?` |
| `emoji_signed.bin` | U+1F600 | pasted as `\u-10179?\u-8704?` | `\fs20 \u-10179?\u-8704?` |
| `emoji_signed.scr` | U+1F600 | pasted as `\u-10179?\u-8704?` | the same as `emoji_signed.bin` |
