#!/usr/bin/env python3
"""Live E2E check for the markdown highlight tweaks in micro-indentwrap.

Runs the real binary in a pty on a sample markdown file, emulates just enough
VT100 (CSI H/f, K/J, SGR, OSC, charset) to record the SGR foreground code and
attributes of every character drawn, then asserts the expected color for each
interesting line.
"""
import os, pty, re, select, sys, time

COLS, ROWS = 100, 40
HERE = os.path.dirname(os.path.realpath(__file__))
MICRO = os.environ.get("MICRO_BIN",
                  os.path.realpath(os.path.expanduser("~/.local/bin/micro-indentwrap")))
SAMPLE = os.path.join(HERE, "sample.md")

CSI = re.compile(r"\x1b\[([0-9;?]*)([a-zA-Z])")
OSC = re.compile(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)")
CHRSET = re.compile(r"\x1b[()][A-Za-z0-9]")


class Grid:
    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.cell_ch = [[" "] * cols for _ in range(rows)]
        self.cell_fg = [[None] * cols for _ in range(rows)]
        self.cell_bg = [[None] * cols for _ in range(rows)]
        self.cell_at = [[0] * cols for _ in range(rows)]
        self.r = self.c = 0
        self.fg = None
        self.bg = None
        self.attrs = 0
        self.pending = ""

    def feed(self, data: bytes):
        s = self.pending + data.decode("utf-8", "ignore")
        # hold back a trailing, still-incomplete escape sequence
        cut = s.rfind("\x1b")
        if cut != -1:
            tail = s[cut:]
            if not any(rx.match(tail) and rx.match(tail).end() == len(tail)
                      for rx in (OSC, CSI, CHRSET)):
                self.pending = tail
                s = s[:cut]
            else:
                self.pending = ""
        i, n = 0, len(s)
        while i < n:
            if s[i] != "\x1b":
                self.put(s[i])
                i += 1
                continue
            for rx in (OSC, CSI, CHRSET):
                m = rx.match(s, i)
                if m:
                    if rx is CSI:
                        self.csi(m.group(1), m.group(2))
                    i = m.end()
                    break
            else:
                i += 1

    def put(self, ch):
        if ch == "\r":
            self.c = 0
            return
        if ch == "\n":
            self.r = min(self.r + 1, self.rows - 1)
            return
        if ch == "\b":
            self.c = max(0, self.c - 1)
            return
        if 0 <= self.r < self.rows and 0 <= self.c < self.cols:
            self.cell_ch[self.r][self.c] = ch
            self.cell_fg[self.r][self.c] = self.fg
            self.cell_bg[self.r][self.c] = self.bg
            self.cell_at[self.r][self.c] = self.attrs
        self.c += 1
        if self.c >= self.cols:
            self.c = self.cols - 1

    def csi(self, params, cmd):
        p = params.rstrip("?")
        nums = [int(x) for x in p.split(";") if x.isdigit()]
        if cmd in ("H", "f"):
            self.r = (nums[0] - 1) if len(nums) > 0 else 0
            self.c = (nums[1] - 1) if len(nums) > 1 else 0
        elif cmd == "A":
            self.r = max(0, self.r - (nums[0] if nums else 1))
        elif cmd == "B":
            self.r = min(self.rows - 1, self.r + (nums[0] if nums else 1))
        elif cmd == "C":
            self.c = min(self.cols - 1, self.c + (nums[0] if nums else 1))
        elif cmd == "D":
            self.c = max(0, self.c - (nums[0] if nums else 1))
        elif cmd == "G":
            self.c = (nums[0] - 1) if nums else 0
        elif cmd == "K":
            for c in range(self.cols):
                self.cell_ch[self.r][c] = " "
                self.cell_fg[self.r][c] = None
                self.cell_bg[self.r][c] = None
        elif cmd == "J":
            for r in range(self.rows):
                for c in range(self.cols):
                    self.cell_ch[r][c] = " "
                    self.cell_fg[r][c] = None
                    self.cell_bg[r][c] = None
        elif cmd == "m":
            self.sgr(nums or [0])

    def sgr(self, nums):
        i = 0
        while i < len(nums):
            v = nums[i]
            if v == 0:
                self.fg, self.bg, self.attrs = None, None, 0
            elif v == 1:
                self.attrs |= 1
            elif v == 2:
                self.attrs |= 2
            elif v == 3:
                self.attrs |= 4
            elif v == 4:
                self.attrs |= 8
            elif v == 7:
                self.attrs |= 16
            elif v == 23:
                self.attrs &= ~4
            elif v == 24:
                self.attrs &= ~8
            elif v == 39:
                self.fg = None
            elif v == 49:
                self.bg = None
            elif v in (38, 48):
                val = None
                if i + 1 < len(nums) and nums[i + 1] == 2 and i + 4 < len(nums):
                    val = f"rgb:{nums[i+2]},{nums[i+3]},{nums[i+4]}"
                    i += 4
                elif i + 1 < len(nums) and nums[i + 1] == 5 and i + 2 < len(nums):
                    val = f"idx:{nums[i+2]}"
                    i += 2
                if val is not None:
                    if v == 38:
                        self.fg = val
                    else:
                        self.bg = val
            elif 30 <= v <= 37:
                self.fg = f"idx:{v-30}"
            elif 40 <= v <= 47:
                self.bg = f"idx:{v-40}"
            elif 90 <= v <= 97:
                self.fg = f"idx:{v-90+8}"
            elif 100 <= v <= 107:
                self.bg = f"idx:{v-100+8}"
            i += 1


def row_text(g, r):
    return "".join(g.cell_ch[r]).rstrip()


def row_runs(g, r):
    runs, cur, start = [], object(), 0
    out = []
    for c in range(g.cols):
        key = (g.cell_fg[r][c], g.cell_at[r][c])
        if cur is not object() and key != cur:
            out.append((cur, "".join(g.cell_ch[r][start:c])))
            start = c
        cur = key
    out.append((cur, "".join(g.cell_ch[r][start:g.cols])))
    return [(f, t) for f, t in out if t.strip()]


def main():
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ["COLORTERM"] = "truecolor"
        # micro's clipboard init (zyedidia/clipper) blocks forever on the Wayland
        # path when driven from a bare pty, which leaves the buffer unloaded and
        # the screen blank. Hide Wayland so it falls back and actually starts.
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.execv(MICRO, ["micro-indentwrap", SAMPLE])
    fcntl_winsize(fd, ROWS, COLS)
    g = Grid(ROWS, COLS)

    def drain(t):
        out, end = b"", time.time() + t
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    break
                g.feed(out)
                out = b""

    drain(1.0)
    # micro only paints after a resize event in a bare pty (the initial size
    # change races with startup), so nudge it and take the frame it draws.
    import signal
    os.kill(pid, signal.SIGWINCH)
    drain(1.5)
    fcntl_winsize(fd, ROWS, COLS + 5)
    drain(1.0)
    fcntl_winsize(fd, ROWS, COLS)
    drain(1.5)
    os.write(fd, b"\x11")  # Ctrl-Q
    time.sleep(0.4)
    try:
        os.close(fd)
    except OSError:
        pass
    os.waitpid(pid, 0)
    return check(g)


def fcntl_winsize(fd, rows, cols):
    import fcntl, termios, struct
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def find_row(g, needle):
    for r in range(g.rows):
        if needle in row_text(g, r):
            return r
    return None


def check(g):
    ok = True
    expectations = [
        ("# Heading one", "idx:15", "bold+italic", "h1 = bright white text, no underline"),
        ("## Heading two", "idx:12", "bold+italic+underline", "h2 = bright blue, underlined"),
        ("### Heading three", "idx:12", "bold+italic+underline", "h3 = bright blue, underlined"),
        ("#### Heading four", "idx:12", "bold+italic", "h4 = bright blue, no underline"),
        ("##### Heading five", "idx:12", "bold+italic", "h5 = bright blue, no underline"),
        ("###### Heading six", "idx:12", "bold+italic", "h6 = bright blue, no underline"),
        ("Just some normal prose text here.", "rgb:242,242,242", "", "normal text #f2f2f2"),
        # NOTE: needles are the bare words, not the **markers**: the emphasis
        # markers are their own gray run (emphasis-marker rule), so no single
        # run contains "**bold**".
        ("bold", "rgb:255,255,255", "bold", "bold = pure white"),
        ("italic", "rgb:255,255,255", "italic", "italic = pure white"),
        ("bolditalic", "rgb:255,255,255", "bold+italic", "bold-italic = pure white"),
        ("code here", "idx:2", "", "inline code = ANSI green"),
        ("# not a heading inside a fence", "idx:2", "", "fenced code = ANSI green"),
        ("<div>not a tag inside a fence</div>", "idx:2", "", "tag inside fence stays green"),
        ("<note>", "idx:4", "", "xml tag = ANSI blue"),
        ("</note>", "idx:4", "", "closing xml tag = ANSI blue"),
        ("<br/>", "idx:4", "", "self-closing tag = ANSI blue"),
    ]
    for needle, want_fg, want_attr, label in expectations:
        r = find_row(g, needle)
        if r is None:
            print(f"FAIL  {label}: line with {needle!r} not found on screen")
            ok = False
            continue
        hits = [(fg, at, txt) for (fg, at), txt in row_runs(g, r) if needle in txt]
        if not hits:
            print(f"FAIL  {label}: no run containing {needle!r}")
            ok = False
            continue
        fg, at, txt = hits[0]
        attrname = "+".join(
            n for bit, n in ((1, "bold"), (4, "italic"), (8, "underline"), (16, "reverse"))
            if at & bit
        ) or "-"
        # exact match when a non-empty attr string is expected, so a stray
        # extra attribute (e.g. an unwanted underline) is caught
        good = fg == want_fg and (want_attr == "" or attrname == want_attr)
        mark = "PASS" if good else "FAIL"
        if not good:
            ok = False
        print(f"{mark}  {label:44s} -> fg={fg} attrs={attrname} {txt.strip()[:40]!r}")

    # Row-fill checks: the patched build must carry h1's blue background and
    # h2's underline all the way to the right edge of the editor, while h3
    # gets neither past its text. Checked on the last column of each row.
    fill_checks = [
        ("# Heading one", "idx:4", False, "h1 row fill = blue bg to right edge"),
        ("## Heading two", "!idx:4", True, "h2 row fill = underline to right edge"),
        ("### Heading three", "!idx:4", False, "h3 = no fill past the text"),
    ]
    for needle, want_bg, want_ul, label in fill_checks:
        r = find_row(g, needle)
        if r is None:
            print(f"FAIL  {label:44s} -> line {needle!r} not found")
            ok = False
            continue
        at = g.cell_at[r][g.cols - 1]
        bg = g.cell_bg[r][g.cols - 1]
        ul = bool(at & 8)
        if want_bg.startswith("!"):
            good = bg != want_bg[1:]
        else:
            good = bg == want_bg
        good = good and ul == want_ul
        mark = "PASS" if good else "FAIL"
        if not good:
            ok = False
        print(f"{mark}  {label:44s} -> last-col bg={bg} underline={ul}")

    # The h1 text itself must sit on the blue background (not just the fill).
    r = find_row(g, "# Heading one")
    if r is None:
        print(f"FAIL  {'h1 text background = blue':44s} -> line not found")
        ok = False
    else:
        col = row_text(g, r).index("# Heading one")
        bg = g.cell_bg[r][col]
        good = bg == "idx:4"
        mark = "PASS" if good else "FAIL"
        if not good:
            ok = False
        print(f"{mark}  {'h1 text background = blue':44s} -> bg={bg}")

    # Wrapped headings: the remainder must stay VISIBLE on continuation rows
    # with the heading style held, and the fill must reach the right edge of
    # every visual row (first row included, where wordwrap pushes a word).
    wrap_checks = [
        ("# Wrap fill h1", "idx:15", False, "idx:4", False, "wrapped h1"),
        ("## Wrap fill h2", "idx:12", True, "!idx:4", True, "wrapped h2"),
    ]
    for needle, want_fg, want_text_ul, want_bg, want_edge_ul, label in wrap_checks:
        r = find_row(g, needle)
        if r is None or r + 1 >= g.rows:
            print(f"FAIL  {label + ' wrap':44s} -> heading row not found")
            ok = False
            continue
        problems = []

        def edge_ok(row):
            at = g.cell_at[row][g.cols - 1]
            bg = g.cell_bg[row][g.cols - 1]
            if want_bg.startswith("!"):
                bg_good = bg != want_bg[1:]
            else:
                bg_good = bg == want_bg
            ul_good = bool(at & 8) == want_edge_ul
            return bg_good, ul_good, bg, bool(at & 8)

        # first visual row: fill reaches the right edge (word-overflow path)
        bg_good, ul_good, bg, ul = edge_ok(r)
        if not bg_good:
            problems.append(f"row1 last-col bg={bg}")
        if not ul_good:
            problems.append(f"row1 last-col underline={ul}")

        # continuation row: heading-colored text must actually be drawn
        cont = r + 1
        cells = [(g.cell_fg[cont][c], g.cell_at[cont][c])
                 for c in range(g.cols) if g.cell_ch[cont][c] != " "]
        styled = [(fg, at) for fg, at in cells if fg == want_fg]
        if not styled:
            problems.append("continuation text missing/invisible")
        elif not any(bool(at & 8) == want_text_ul for fg, at in styled):
            problems.append("continuation text underline wrong")

        # continuation row: fill reaches the right edge too
        bg_good, ul_good, bg, ul = edge_ok(cont)
        if not bg_good:
            problems.append(f"cont last-col bg={bg}")
        if not ul_good:
            problems.append(f"cont last-col underline={ul}")

        good = not problems
        mark = "PASS" if good else "FAIL"
        if not good:
            ok = False
        detail = "ok" if good else "; ".join(problems)
        print(f"{mark}  {(label + ' wrap: style + fill held'):44s} -> {detail}")

    print()
    print("screen dump (row: text | fg runs):")
    for r in range(g.rows):
        t = row_text(g, r)
        if not t:
            continue
        runs = ", ".join(
            f"{fg}/{'+'.join(n for bit, n in ((1, 'bold'), (4, 'italic'), (8, 'ul'), (16, 'rev')) if at & bit) or '-'}"
            for (fg, at), _ in row_runs(g, r)
        )
        print(f"  {r:2d}: {t[:70]}")
        print(f"      {runs}")
    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
