# TM-U295 capabilities

Every command in Epson's TM-U295 specification (Rev. I), and where this project exposes it. Anything listed can also be sent directly with `slip send` (Epson notation, checked against the printer's command table), e.g. `slip send ESC p 0 50 250`.

## Supported commands

| Command | What it does | Exposed as |
|---|---|---|
| `HT` | next tab stop | `slip send` (templates position with the column grid instead) |
| `LF` | print, feed one line | used by every template |
| `CR` | ignored by the serial model | `slip send` (no effect) |
| `FF` | eject the slip; in page mode, print the page | `finish: eject` (the default), `slip eject`; ends rotated layouts |
| `CAN` | clear the page-mode area | `slip send` |
| `DLE EOT` | real-time status (n = 1, 2, 3, 5) | `slip status`, the print guard, the web UI status |
| `ESC SP` | extra space after each character | template `char_spacing` (reduces the column count) |
| `ESC !` | font, double height/width, underline | template `font`; styles `double_height`, `double_width`, `underline` |
| `ESC %` | select user-defined characters | template `characters` |
| `ESC &` | define user-defined characters | template `characters` (5x7, 7 rows of 5) |
| `ESC *` | 8-dot bit image, 80 or 160 dpi | `slip image`; template `images` (`density`, `width`, `dither`, `threshold`, `aspect`) |
| `ESC 2` | line spacing 1/6" | template default |
| `ESC 3` | line spacing n/60" | template `line_spacing` |
| `ESC =` | enable/disable the printer | `slip send` |
| `ESC @` | initialize | sent before every job |
| `ESC C` | eject length | template `eject: {length}` |
| `ESC D` | set tab stops | `slip send` (templates position with the column grid instead) |
| `ESC F` | eject direction | template `eject: {reverse: true}` |
| `ESC J` | print, feed n/60" | double-height lines and image bands |
| `ESC K` | print, reverse feed n/60" | `slip send` |
| `ESC L` | enter page mode | `orientation: rotated` |
| `ESC R` | international character set | template `international` |
| `ESC T` | page-mode direction | rotated `page: {direction}` |
| `ESC W` | page-mode print area | rotated `page: {width, height}` |
| `ESC c 3` | paper-end signal sensors (ignored by the serial model) | `slip send` (no effect) |
| `ESC c 4` | stop printing at paper end | always on for every job (both sensors) |
| `ESC c 5` | enable/disable panel buttons | `slip buttons enable|disable` |
| `ESC d` | print, feed n lines | `slip send` |
| `ESC e` | print, reverse feed n lines | the `bold` style (overstrike) |
| `ESC f` | delay after slip insertion | template `insert_delay` |
| `ESC p` | cash drawer pulse | template `drawer`, `slip drawer` |
| `ESC q` | release the slip | template `finish: release`, `slip release` |
| `ESC t` | code page (PC437, Katakana, PC850, PC858) | template `codepage` |
| `ESC u` | drawer status | `slip send` (the drawer pin is also in `DLE EOT 1`) |
| `ESC v` | paper sensor status | `slip send` (`DLE EOT 5` is used instead: it's answered even while a job is queued) |
| `ESC {` | upside-down printing | template `upside_down` |
| `GS I` | printer ID | `slip info` |
| `GS a` | automatic status back | `slip send` (status is polled with `DLE EOT` instead) |
| `GS r` | transmit status | `slip send` (`DLE EOT` is used instead) |

## Not supported by the TM-U295

`slip send` refuses these and says what to use instead.

| Command | Instead |
|---|---|
| `GS V`, `ESC i`, `ESC m` (cut) | no cutter; slips are ejected with `FF` |
| `ESC E` (emphasized), `ESC G` (double-strike) | the `bold` style, an overstrike |
| `ESC -` (underline) | the `underline` style (`ESC !` bit 7) |
| `ESC M` (font) | template `font: 7x7` (`ESC !` bit 0) |
| `GS !` (character size) | styles `double_width`, `double_height` |
| `ESC a` (justification) | `col`, or `align: right` |
| `ESC $`, `ESC \` (positioning) | the line × column grid |
| `ESC V` (90° rotation) | `orientation: rotated` (page mode) |
| `GS k` (barcodes) | not possible |
| `GS v 0`, `GS *`, `GS /`, `GS (` (raster, downloaded and extended graphics) | template `images` (`ESC *`) |
| `ESC r` (color) | single-color ribbon |
| `DLE ENQ`, `DLE DC4` | `DLE EOT` for status, `slip drawer` for the drawer |

## Limits worth knowing

- The print band is 65.8 mm wide: 35 columns in the 5x7 font, 42 in 7x7. Check fronts need `orientation: rotated`.
- Page mode (rotated layouts) ignores underline and refuses reverse feed, so `underline` and `bold` aren't available there.
- The head can't feed less than 8/60" per line, so `line_spacing` is at least 8.
- To verify on paper (issue #9): the bit order of custom characters, image alignment with the text grid, and the international character tables.
