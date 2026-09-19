# Micro Soft Wrap Indent Overlay

This directory contains a non-destructive overlay that builds a separate Micro
binary with soft-wrapped continuation rows visually aligned to the line's
leading indentation.

The system Micro binary at `/usr/bin/micro` is not modified. The overlay builds
`~/.local/bin/micro-indentwrap` from a clean upstream Micro checkout plus the
patches in `patches/` (applied in alphabetical order).

## Files

`build-micro-indentwrap.sh`

: Clones Micro, applies every `patches/*.patch` in order, runs focused tests,
  builds Micro, and installs the result as `~/.local/bin/micro-indentwrap`.

`patches/micro-indentwrap-v2.0.15.patch`

: The indent-wrap feature patch. It targets upstream Micro `v2.0.15`.

`patches/micro-mdhead-title-v2.0.15.patch`

: Applies on top of the indentwrap patch. Two changes:
  - Markdown h1 lines (`# ` + at least one character of content) get their
    trailing padding — and softwrap continuation rows — drawn with an
    underline in the `headline` colorscheme foreground, so the underline
    spans the full editor width with no gap after the text. The newline
    cell is styled too. Detection requires the syntax engine to classify
    the line's first character as the "headline" group, so `#` lines inside
    fenced code blocks are excluded. h2–h6 are styled text-only via the
    syntax file/colorscheme (no patch needed for those). Fill color follows
    `color-link headline`, defaulting to blue.
  - Sets the terminal window/tab title to plain `micro` by emitting OSC 0
    directly after screen init (the vendored tcell fork has no `SetTitle`).
    The title no longer derives from the binary name.

`patches/micro-wrapfix-exactfill-v2.0.15.patch`

: Applies last (filename sorts after the others). Fixes the upstream
  "phantom row": a softwrapped line whose visible width exactly equals the
  pane width used to get an extra empty, unnumbered row below it (upstream
  still does this on master). With this patch such a line occupies exactly
  one row — the next line draws directly beneath it, and the end-of-line
  cursor renders on the row's last cell instead of on a blank row below.
  Drawing (`bufwindow.go`), buffer-to-visual mapping (`getVLocFromLoc`),
  and end-of-line cursor rendering were changed in lockstep so scrolling,
  `Relocate`, and mouse-click mapping stay consistent. Adds
  `internal/display/softwrap_test.go` (unit tests for the exact-fill edge,
  wrap mapping round-trips, and click mapping).

`settings.json`

: Contains `"softwrap": true`, `"wordwrap": true`, and `"indentwrap": true`.
  The stock Micro binary ignores `indentwrap`; the patched binary uses it.

## User Behavior

The feature is controlled by a new common Micro option:

```json
"indentwrap": true
```

It only matters when `softwrap` is also enabled. With `indentwrap` enabled, a
physical line like this:

```text
    a long line of text that wraps because the pane is narrow
```

is displayed like this:

```text
    a long line of text that wraps
    because the pane is narrow
```

The extra indentation on continuation rows is virtual. It is drawn on screen
only. It is not inserted into the buffer, written to disk, copied, searched,
linted, formatted, or added to undo history.

The indent is recalculated on redraw from the current line text and pane width.
Terminal resize, split resize, `tabsize` changes, edits to indentation, and
softwrap recalculation all naturally update the displayed continuation rows.

### Exact-fill lines (wrapfix patch)

Upstream Micro reserves an extra blank row under any line that exactly fills
the pane width, so the end-of-line cursor has a cell to render on. With
`indentwrap` that blank row also got the virtual indent drawn on it and the
cursor parked after the indent — it looked exactly like a stray auto-indented
blank line, especially right after pressing Enter at the end of such a line.
The wrapfix patch removes that phantom row entirely: the line occupies one
row, the next line sits directly below it, and the end-of-line cursor draws
on the row's last cell (same as most GUI editors). Buffer contents were and
remain correct in all cases — the phantom row was display-only.

## Implementation

Micro's Lua plugin API cannot implement this correctly because soft wrapping is
not exposed as a plugin hook. The relevant behavior lives in Micro's Go display
layer:

`internal/display/bufwindow.go`

: Draws buffer text into terminal cells.

`internal/display/softwrap.go`

: Converts between buffer positions and visual wrapped positions for cursor
  movement, mouse clicks, scrolling, and selection behavior.

`internal/config/settings.go`

: Defines built-in options.

The patch adds a boolean common option named `indentwrap`, defaulting to
`false`.

When drawing a line, the patched renderer computes the visual width of the
line's leading spaces and tabs using Micro's existing `tabsize` rules. When a
soft wrap occurs, continuation rows draw virtual spaces before drawing the next
real character. The virtual indent is capped at `pane width - 1` so deeply
indented lines still have at least one column available for content.

The same indent calculation is also applied in `softwrap.go`. This is the
critical part: drawing alone would make the screen look right but would break
cursor movement, mouse clicks, scrolling, and visual position calculations.

The patched option callback treats `indentwrap` like `softwrap` and `wordwrap`.
When it changes, Micro relocates the viewport and recalculates wrapped cursor
columns.

## Build And Use

Build the patched binary:

```bash
~/.config/micro/build-micro-indentwrap.sh
```

Run it directly:

```bash
~/.local/bin/micro-indentwrap file.md
```

Or put `~/.local/bin` before `/usr/bin` in your shell `PATH` and use an alias:

```bash
alias microw='~/.local/bin/micro-indentwrap'
```

To rebuild without running the focused tests:

```bash
RUN_TESTS=0 ~/.config/micro/build-micro-indentwrap.sh
```

## Verification

The build script runs:

```bash
go test ./internal/display ./internal/config ./internal/buffer ./internal/action
```

`internal/display/softwrap_test.go` (from the wrapfix patch) unit-tests the
exact-fill edge: no phantom row, row counts, mid-line wraps, indentwrap
continuations, loc↔vloc round-trips, and click mapping. The softline
Home/End patch has its own E2E suite at `~/.config/micro/verify-softline-homeend.py`
(pty-based, tests the installed binary; run it after rebuilding).

Final behavior should also be checked manually in a narrow terminal pane:

1. Open a file with indented long lines.
2. Confirm continuation rows start at the line's leading indentation.
3. Confirm a line that exactly fills the pane width has NO blank row under
   it, and Enter at its end puts the new line directly below.
4. Resize the terminal and confirm wraps recalculate.
5. Click in and around wrapped rows and confirm cursor placement is coherent.
6. Save the file and confirm no extra indentation was written.

## If Micro Updates Break The Patch

This overlay is intentionally small, but it touches Micro internals. A future
Micro release may change the display code enough that the patch no longer
applies.

If `build-micro-indentwrap.sh` fails at `git apply`, do this:

1. Clone the target Micro version:

```bash
git clone --branch vNEW_VERSION https://github.com/zyedidia/micro.git /tmp/micro-indentwrap-update
```

2. Inspect the patch targets (each patch lists its files under `patches/`;
   between them: `settings.go`, `bufwindow.go`, `softwrap.go`,
   `softwrap_test.go`, `actions.go`, `screen.go`, `runtime/help/options.md`):

```bash
cd /tmp/micro-indentwrap-update
less internal/config/settings.go
less internal/display/bufwindow.go
less internal/display/softwrap.go
```

3. Reapply the same design:

- Add `indentwrap` as a common boolean option, default `false`.
- Recalculate wrapped cursor columns when `indentwrap` changes.
- Compute leading whitespace width with existing tab rules.
- Draw virtual indent cells on continuation rows only.
- Apply the same row-start indent in buffer-to-visual and visual-to-buffer
  mapping.
- Keep the cap at `pane width - 1`.
- No phantom row on exact-fill lines: only wrap the display when content
  remains (`len(line) > 0`), count rows the same way, and render the
  end-of-line cursor on the row's last cell.

4. Run formatting and tests:

```bash
gofmt -w internal/config/settings.go internal/display/bufwindow.go internal/display/softwrap.go internal/display/softwrap_test.go
go test ./internal/display ./internal/config ./internal/buffer ./internal/action
make build
```

5. Regenerate the patches. The build script applies `patches/*.patch` in
   alphabetical order, and each patch's context assumes the earlier ones are
   already applied — keep the naming order (indentwrap, mdhead-title,
   softline-homeend, wrapfix-exactfill). Generate each patch against the
   tree state after the patches that precede it, e.g. stage the applied
   state with `git add -A`, apply/keep only the next patch's changes as
   unstaged work, then `git diff > patches/<name>.patch`. Untracked files
   (such as `internal/display/softwrap_test.go`) need `git add -N` before
   they appear in `git diff`.

6. Run the build script from a directory outside the source tree (it deletes
   and re-clones the source):

```bash
cd ~ && ~/.config/micro/build-micro-indentwrap.sh
```

If the patch applies but behavior is wrong, the most likely cause is that
Micro changed its wrap algorithm. Compare the current upstream logic in
`bufwindow.go` and `softwrap.go` and make sure both files still use identical
rules for row starts, word wrapping, wide runes, and tab expansion.

## Known Tradeoffs

Very deep indentation reduces available continuation width. This is expected:
the feature follows indentation visually, so fewer columns remain for content.
The cap prevents total starvation.

The feature follows leading whitespace only. It does not implement semantic
hanging indents for Markdown list markers, block quotes, comments, or language
syntax. That would be a separate, more opinionated layer.

Clicking inside the virtual indent maps to the nearest real buffer position on
that wrapped row. The virtual cells are not selectable text.

The wrapfix patch intentionally diverges from upstream Micro (which still
shows the exact-fill phantom row on master). If this overlay is ever rebased
onto a newer Micro, check whether upstream changed the end-of-line wrap/cursor
handling first — if it fixed the phantom row itself, the wrapfix patch can
simply be dropped.
