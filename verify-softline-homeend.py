#!/usr/bin/env python3
"""E2E: softline Home/End in micro-indentwrap via pty + minimal terminal emulator.

Phase 1 — one long wrapped line: End/Home walk the wrapped rows and stop at the
          logical line end / col 1.
Phase 2 — multi-line file (wrapped lines + short + empty): End/Home traverse
          across hard line breaks to the buffer end and back, visiting the
          empty line's row end on the way.

Reads cursor position from the statusline ("filename (line,col)").
"""
import os, pty, re, select, sys, time, tempfile
import fcntl, termios, struct

COLS, ROWS = 60, 20
END, HOME = b"\x1b[4~", b"\x1b[H"
MICRO_BIN = os.path.realpath(os.path.expanduser("~/.local/bin/micro-indentwrap"))

class Grid:
    """Just enough VT100 for tcell's output: CSI H/f, K, J, SGR, OSC, charset."""
    CSI = re.compile(r"\x1b\[([0-9;?]*)([a-zA-Z])")
    OSC = re.compile(r"\x1b\][^\x07]*\x07")
    CHR = re.compile(r"\x1b[()][A-Za-z0-9]")

    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.buf = [[" "] * cols for _ in range(rows)]
        self.r = self.c = 0
        self.pending = ""

    def feed(self, data: bytes):
        s = self.pending + data.decode("utf-8", "ignore")
        carry = ""
        for m in (self.OSC, self.CSI, self.CHR):
            tail = s[s.rfind("\x1b"):]
            if "\x1b" in s and not m.search(tail) and len(tail) < 32:
                carry = tail
                s = s[: len(s) - len(tail)]
                break
        i, n = 0, len(s)
        while i < n:
            ch = s[i]
            if ch == "\x1b":
                m = self.OSC.match(s, i)
                if m:
                    i = m.end(); continue
                m = self.CSI.match(s, i)
                if m:
                    self.csi(m.group(1), m.group(2))
                    i = m.end(); continue
                m = self.CHR.match(s, i)
                if m:
                    i = m.end(); continue
                i += 1; continue
            if ch == "\r":
                self.c = 0
            elif ch == "\n":
                self.r = min(self.r + 1, self.rows - 1)
            elif ch == "\b":
                self.c = max(0, self.c - 1)
            else:
                self.put(ch)
            i += 1
        self.pending = carry

    def put(self, ch):
        if 0 <= self.r < self.rows and 0 <= self.c < self.cols:
            self.buf[self.r][self.c] = ch
        self.c += 1

    def csi(self, params, cmd):
        ps = [int(x) for x in params.split(";") if x.isdigit()]
        if cmd in ("H", "f"):
            self.r = (ps[0] - 1) if len(ps) > 0 and ps[0] > 0 else 0
            self.c = (ps[1] - 1) if len(ps) > 1 and ps[1] > 0 else 0
        elif cmd == "K":
            mode = ps[0] if ps else 0
            if mode == 0:
                for c in range(self.c, self.cols): self.buf[self.r][c] = " "
            elif mode == 2:
                for c in range(self.cols): self.buf[self.r][c] = " "
        elif cmd == "J" and ps and ps[0] == 2:
            self.buf = [[" "] * self.cols for _ in range(self.rows)]

    def text(self, row):
        return "".join(self.buf[row]).rstrip()


failures = 0
def check(name, cond, detail=""):
    global failures
    print(("PASS  " if cond else "FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures += 1


def run_session(file_text, keys):
    """Open micro on file_text, apply keys; returns list of (line,col) after each key."""
    home = tempfile.mkdtemp(prefix="micro-e2e-")
    os.makedirs(f"{home}/.config/micro")
    with open(f"{home}/.config/micro/settings.json", "w") as f:
        f.write('{"softwrap": true, "wordwrap": true}\n')
    with open(f"{home}/test.txt", "w") as f:
        f.write(file_text)

    pid, fd = pty.fork()
    if pid == 0:
        os.environ["HOME"] = home
        os.environ["TERM"] = "xterm-256color"
        os.execv(MICRO_BIN, ["micro-indentwrap", f"{home}/test.txt"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    grid = Grid(ROWS, COLS)

    def drain(t=0.35):
        out, end = b"", time.time() + t
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    break
        grid.feed(out)

    def pos():
        for row in range(ROWS - 1, ROWS - 4, -1):
            m = re.search(r"\((\d+),(\d+)\)", grid.text(row))
            if m:
                return int(m.group(1)), int(m.group(2))
        return None

    drain(1.5)
    positions = [pos()]
    for key in keys:
        os.write(fd, key)
        drain()
        positions.append(pos())

    os.write(fd, b"\x11")  # ctrl+q quit
    drain(0.3)
    os.close(fd)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    return positions


# --- Phase 1: single wrapped line -------------------------------------------
LINE = " ".join(f"word{i:02d}" for i in range(1, 13))  # ~85 chars, wraps at 60 cols
LINELEN = len(LINE)
pos = run_session(LINE, [END] * 4 + [HOME] * 4)  # no trailing \n: buffer ends at the logical EOL

check("starts at (1,1)", pos[0] == (1, 1), str(pos[0]))
end_walk = []
for p in pos[1:5]:
    if p is None or (end_walk and p == end_walk[-1]):
        break
    end_walk.append(p)
check("End walk strictly increases", all(a < b for a, b in zip(end_walk, end_walk[1:])), str(end_walk))
check("End reaches logical EOL", end_walk and end_walk[-1] == (1, LINELEN + 1), f"{end_walk[-1] if end_walk else None} want {(1, LINELEN+1)}")
check("End took multiple steps (line wrapped)", len(end_walk) >= 2, str(end_walk))

home_walk = []
for p in pos[5:9]:
    if p is None or (home_walk and p == home_walk[-1]):
        break
    home_walk.append(p)
check("Home walk strictly decreases", all(a > b for a, b in zip(home_walk, home_walk[1:])), str(home_walk))
check("Home reaches (1,1)", home_walk and home_walk[-1] == (1, 1), str(home_walk))

# --- Phase 2: traverse across hard line breaks -------------------------------
TEXT = ("first line that is long enough to wrap at sixty columns for sure yes\n"
        "short\n"
        "\n"
        "third line also long enough to wrap around the sixty column mark ok")
LINES = TEXT.split("\n")
pos = run_session(TEXT, [END] * 10 + [HOME] * 10)

end_walk = []
for p in pos[1:11]:
    if p is None or (end_walk and p == end_walk[-1]):
        break
    end_walk.append(p)
want_end = (len(LINES), len(LINES[-1]) + 1)
check("End walk reaches buffer end", end_walk[-1] == want_end, f"{end_walk[-1]} want {want_end}; path={end_walk}")
check("End walk crossed hard line breaks", len({p[0] for p in end_walk}) >= 2, str(end_walk))
check("End walk visited the empty line's row end", (3, 1) in end_walk, str(end_walk))

home_walk = []
for p in pos[11:21]:
    if p is None or (home_walk and p == home_walk[-1]):
        break
    home_walk.append(p)
check("Home walk returns to (1,1)", home_walk[-1] == (1, 1), f"{home_walk[-1]}; path={home_walk}")
check("Home walk crossed hard line breaks", len({p[0] for p in home_walk}) >= 2, str(home_walk))

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
sys.exit(1 if failures else 0)
