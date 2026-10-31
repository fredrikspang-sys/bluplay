#!/usr/bin/env python3
"""End-to-end smoke test for bluplay against the fake player (never a real device).

usage: tests/smoke.py [BINARY]        (default ./bluplay; run from the repo root, e.g. "make test")
needs: python3 and the 'pyte' terminal emulator module (pip install pyte) for the UI part;
       without pyte only the command-line checks run.
"""
import os, sys, re, pty, time, fcntl, termios, struct, select, signal, socket, subprocess, tempfile, urllib.request, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "./bluplay")
BAD = re.compile(rb"AddressSanitizer|runtime error|LeakSanitizer|Segmentation|SUMMARY:|core dumped")
try:
    import pyte
except ImportError:
    pyte = None

fails = 0; total = 0
def ok(name, cond, detail=""):
    global fails, total
    total += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "   " + str(detail)))
    if not cond: fails += 1

def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

PORT = free_port(); MPORT = free_port(socket.SOCK_DGRAM); DEAD = free_port(socket.SOCK_DGRAM)
TMP = tempfile.mkdtemp(prefix="bluplay-test-")
fake = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_player.py"), str(PORT)], env=dict(os.environ, FAKE_QN="20"),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
mdns = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_mdns.py"), str(MPORT),
                         "Living Room=127.0.0.1:%d" % PORT, "Kitchen=127.0.0.2:%d/_musp" % PORT],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def srv(path): return urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=10).read().decode()
def status():
    x = srv("/Status"); g = lambda t: (re.search("<%s>(.*?)</%s>" % (t, t), x) or [None, ""])[1]
    return dict(state=g("state"), db=int(g("db") or 0), song=int(g("song") or -1), secs=int(g("secs") or 0))
def qlen(): return len(re.findall(r"<song ", srv("/Playlist")))
for _ in range(100):
    try: srv("/SyncStatus"); break
    except Exception: time.sleep(0.05)

def env(**kw):
    e = {k: v for k, v in os.environ.items() if not k.startswith("BLUPLAY_") and k != "XDG_CONFIG_HOME"}
    e.update(HOME=TMP, LANG="C.UTF-8", LC_ALL="C.UTF-8", ASAN_OPTIONS="detect_leaks=0", BLUPLAY_MDNS_ADDR="127.0.0.1:%d" % DEAD)
    e.update(kw); return e
def run(args, timeout=20, **kw):
    p = subprocess.run([BIN] + args, env=env(**kw), stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
HOSTARG = "127.0.0.1:%d" % PORT

try:
    # ---- command line, configuration, discovery
    rc, out, err = run(["--version"]); ok("--version", rc == 0 and out.startswith("bluplay "), (rc, out))
    rc, out, err = run(["--help"]); ok("--help", rc == 0 and "BLUPLAY_HOST" in out and "--discover" in out, rc)
    rc, out, err = run(["--bogus"]); ok("unknown option -> exit 2", rc == 2 and "unknown option" in err, (rc, err))
    rc, out, err = run(["--status", "--no-discover"]); ok("nothing configured, discovery off -> help message", rc == 1 and "no BluOS player configured" in err and "--host" in err, (rc, err))
    os.makedirs(os.path.join(TMP, "emptybin"), exist_ok=True)
    rc, out, err = run(["--status"], PATH=os.path.join(TMP, "emptybin")); ok("discovery finds nothing -> help message", rc == 1 and "none was found" in err, (rc, err))
    rc, out, err = run(["--discover"], BLUPLAY_MDNS_ADDR="127.0.0.1:%d" % MPORT)
    ok("--discover lists both players", rc == 0 and "Living Room" in out and "Kitchen" in out and out.index("Living Room") < out.index("Kitchen") and HOSTARG in out, (rc, out, err))
    rc, out, err = run(["--status"], BLUPLAY_MDNS_ADDR="127.0.0.1:%d" % MPORT)
    ok("--status via discovery uses first player", rc == 0 and "player=" + HOSTARG in out and "using Living Room" in err and "first of several" in err, (rc, out, err))
    rc, out, err = run(["--status", "--host", HOSTARG]); ok("--status --host", rc == 0 and "state=play" in out and "file=/mnt/music/" in out, (rc, out, err))
    rc, out, err = run(["--status", "-H", "127.0.0.1", "-p", str(PORT)]); ok("--status -H host -p port", rc == 0 and "state=play" in out, (rc, err))
    rc, out, err = run(["--status"], BLUPLAY_HOST="127.0.0.1", BLUPLAY_PORT=str(PORT)); ok("env BLUPLAY_HOST + BLUPLAY_PORT", rc == 0 and "state=play" in out, (rc, err))
    cfgdir = os.path.join(TMP, ".config", "bluplay"); os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "config"), "w") as f: f.write("# test\nhost = 127.0.0.1    # inline comment\nport = \"%d\"\ndb_offset = -10\n" % PORT)
    rc, out, err = run(["--status"]); ok("config file host/port + db_offset", rc == 0 and "state=play" in out and "db=-50.0 dB" in out, (rc, out, err))
    rc, out, err = run(["--status"], BLUPLAY_HOST="127.0.0.1:1"); ok("env overrides config (bad host fails)", rc == 1, (rc, out))
    rc, out, err = run(["--status", "--host", HOSTARG], BLUPLAY_HOST="127.0.0.1:1"); ok("flag overrides env", rc == 0, (rc, err))
    with open(os.path.join(TMP, "alt.conf"), "w") as f: f.write("host=127.0.0.1:%d\nfoo=bar\n" % PORT)
    rc, out, err = run(["--status", "-c", os.path.join(TMP, "alt.conf")], HOME=os.path.join(TMP, "nohome"))
    ok("-c FILE, unknown key warns", rc == 0 and "unknown setting 'foo'" in err, (rc, err))
    os.remove(os.path.join(cfgdir, "config"))
    rc, out, err = run(["--group", "127.0.0.9", "--host", HOSTARG]); ok("--group adds a player", rc == 0 and 'slave id="127.0.0.9" port="11000"' in srv("/SyncStatus"), (rc, err))
    rc, out, err = run(["--ungroup", "127.0.0.9", "--host", HOSTARG]); ok("--ungroup removes it", rc == 0 and "slave" not in srv("/SyncStatus"), (rc, err))
    rc, out, err = run(["--seek", "100", "--host", HOSTARG]); ok("--seek 100", rc == 0 and 100 <= status()["secs"] <= 102, (rc, err, status()))
    rc, out, err = run(["--seek", "-30", "--host", HOSTARG]); ok("--seek -30 (relative)", rc == 0 and 70 <= status()["secs"] <= 73, (rc, err, status()))
    rc, out, err = run(["--queue", "--host", HOSTARG]); ok("--queue lists 20 tracks", rc == 0 and len(out.strip().splitlines()) == 20, (rc, out[:200]))

    # ---- full-screen UI in a pseudo-terminal
    if pyte is None:
        print("skip UI tests (python module 'pyte' not installed)")
    else:
        rows, cols = 30, 110
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(BIN, [BIN, "--host", HOSTARG], dict(env(BLUPLAY_MDNS_ADDR="127.0.0.1:%d" % MPORT), TERM="xterm-256color"))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        scr = pyte.Screen(cols, rows); stream = pyte.ByteStream(scr); raw = [b""]
        def pump(t):
            end = time.time() + t
            while time.time() < end:
                r, _, _ = select.select([fd], [], [], 0.05)
                if r:
                    try: d = os.read(fd, 65536)
                    except OSError: return False
                    if not d: return False
                    raw[0] += d; stream.feed(d)
            return True
        def text(): return "\n".join(scr.display)
        def wait(pred, t=5.0):
            end = time.time() + t
            while time.time() < end:
                try:
                    if pred(): return True
                except Exception: pass
                pump(0.1)
            return pred()
        def key(b, settle=0.4): os.write(fd, b); pump(settle)
        wait(lambda: "Queue (20)" in text() and "Alpha" in text(), 8)
        ok("UI: start screen (album list + queue)", "Queue (20)" in text() and "Albums" in scr.display[2] and "Alpha" in text(), text())
        if os.environ.get("SMOKE_SCREEN"):   # save a text capture of the start screen
            with open(os.environ["SMOKE_SCREEN"], "w") as f: f.write("\n".join(l.rstrip() for l in scr.display) + "\n")
        ok("UI: title line shows playing track", "Track 1" in scr.display[0], scr.display[0])
        ok("UI: progress bar on status line", re.search(r" \[ {5,}\] +\d+:\d\d/3:20 ", scr.display[1]) and (lambda r, e: r[e - 1].bg == "bcbcbc" and r[e - 1].underscore and r[e].bg == "bcbcbc")(scr.buffer[1], scr.display[1].index("] ")) and all(scr.buffer[y][x].bg == "bcbcbc" and scr.buffer[y][x].fg == "000000" for y in (0, 1) for x in (0, cols - 2)) and scr.buffer[3][0].bg == "default", scr.display[1])
        key(b"?"); ok("UI: ? shows help", "bluplay 0.1.0 - help" in text() and "multi-select" in text().lower(), text())
        key(b"x"); ok("UI: any key closes help", "Queue (20)" in text(), text())
        key(b"G"); ok("UI: G lists other players", wait(lambda: "1 [ ] Kitchen" in scr.display[-1] and "Living Room" not in scr.display[-1], 6), scr.display[-1])
        key(b"1"); ok("UI: 1 groups Kitchen", wait(lambda: "1 [x] Kitchen" in scr.display[-1]) and 'slave id="127.0.0.2"' in srv("/SyncStatus"), scr.display[-1])
        key(b"1"); ok("UI: 1 again ungroups", wait(lambda: "1 [ ] Kitchen" in scr.display[-1]) and "slave" not in srv("/SyncStatus"), scr.display[-1])
        key(b"\x1b", 0.6); ok("UI: Esc closes group list", "Ungrouped: Kitchen" in scr.display[-1], scr.display[-1])
        ok("UI: queue header shows shuffle/repeat", wait(lambda: "Shuffle: OFF  Repeat: off" in scr.display[2]), scr.display[2])
        key(b"s"); ok("UI: s turns shuffle on", wait(lambda: "<shuffle>1</shuffle>" in srv("/Status") and "Shuffle: ON" in scr.display[2]), scr.display[2])
        key(b"s"); ok("UI: s again turns it off", wait(lambda: "<shuffle>0</shuffle>" in srv("/Status") and "Shuffle: OFF" in scr.display[2]), scr.display[2])
        for v, nm in ((0, "queue"), (1, "track"), (2, "off")):
            key(b"t"); ok("UI: t cycles repeat to %s" % nm, wait(lambda: "<repeat>%d</repeat>" % v in srv("/Status") and ("Repeat: " + nm) in scr.display[2]), scr.display[2])
        key(b"m"); ok("UI: m mutes (level kept)", wait(lambda: "<mute>1</mute>" in srv("/Status") and " MUTED" in scr.display[1]) and status()["db"] == -40, scr.display[1])
        key(b"m"); ok("UI: m again unmutes", wait(lambda: "<mute>0</mute>" in srv("/Status") and "MUTED" not in scr.display[1]), scr.display[1])
        for v in ("15", "30", "45", "60", "90"):
            key(b"z"); ok("UI: z sets sleep %s min" % v, wait(lambda: "<sleep>%s</sleep>" % v in srv("/Status") and ("sleep %sm" % v) in scr.display[1]), scr.display[1])
        key(b"z"); ok("UI: z cycles sleep back to off", wait(lambda: "<sleep></sleep>" in srv("/Status") and "sleep " not in scr.display[1]), scr.display[1])
        key(b"S"); ok("UI: S stops", wait(lambda: status()["state"] == "stop"), status())
        key(b" "); ok("UI: space plays after stop", wait(lambda: status()["state"] == "play"), status())
        key(b" "); ok("UI: space pauses", wait(lambda: status()["state"] == "pause"), status())
        key(b" "); ok("UI: space resumes", wait(lambda: status()["state"] == "play"), status())
        db0 = status()["db"]; key(b"+"); ok("UI: + raises volume 2 dB", wait(lambda: status()["db"] == db0 + 2), (db0, status()))
        key(b"-"); ok("UI: - lowers volume", wait(lambda: status()["db"] == db0), status())
        ok("UI: volume shown in dB", wait(lambda: ("vol %d.0 dB" % db0) in scr.display[1]), scr.display[1])
        s0 = status()["secs"]; key(b"."); ok("UI: . seeks forward 10 s", wait(lambda: s0 + 9 <= status()["secs"] <= s0 + 13), (s0, status()))
        s0 = status()["secs"]; key(b","); ok("UI: , seeks back 10 s", wait(lambda: s0 - 11 <= status()["secs"] <= s0 - 7), (s0, status()))
        key(b"n"); ok("UI: n skips to next", wait(lambda: status()["song"] == 1), status())
        key(b"\r"); ok("UI: Enter opens album", wait(lambda: "Albums/" in scr.display[2] and scr.display[3].startswith("01 ")), text())
        n0 = qlen(); key(b"a"); ok("UI: a adds track to queue", wait(lambda: qlen() == n0 + 1) and wait(lambda: "Queue (%d)" % (n0 + 1) in text()), (n0, qlen()))
        key(b"h"); ok("UI: h goes up to album list", wait(lambda: scr.display[2].startswith("Library/Albums ") and "Albums/" not in scr.display[2]), scr.display[2])
        key(b"/"); key(b"zul"); key(b"\r")
        ok("UI: / filter", wait(lambda: "[/zul]" in scr.display[2] and "Zulu" in scr.display[3]), text())
        key(b"h"); ok("UI: h clears filter", wait(lambda: "[/" not in scr.display[2]), scr.display[2])
        key(b"g"); key(b"t")
        ok("UI: g+letter jumps", wait(lambda: any(l.startswith("Tango") for l in scr.display[3:])), text())
        key(b"h"); ok("UI: h to library root", wait(lambda: "Artists" in text() and "Library" in scr.display[2]), scr.display[2])
        key(b"\x1b[C"); key(b"\x1b[D")
        key(b"j"); key(b"\r"); ok("UI: re-open Albums from root", wait(lambda: "Albums" in scr.display[2] and "Alpha" in text()), scr.display[2])
        n0 = qlen(); key(b"\t"); key(b"d")
        ok("UI: Tab + d removes one track", wait(lambda: qlen() == n0 - 1) and wait(lambda: "Queue (%d)" % (n0 - 1) in text()), (n0, qlen()))
        n0 = qlen(); key(b"\x1b[1;2B"); key(b"\x1b[1;2B")
        ok("UI: Shift+Down x2 selects 3", "3 selected" in scr.display[2], scr.display[2])
        key(b"d"); ok("UI: d with selection asks", "Remove 3 selected tracks" in text(), scr.display[-1])
        key(b"y"); ok("UI: y removes 3", wait(lambda: qlen() == n0 - 3) and wait(lambda: "Queue (%d)" % (n0 - 3) in text()), (n0, qlen()))
        key(b"v"); key(b"j"); ok("UI: v select mode", "2 selected" in scr.display[2], scr.display[2]); key(b"\x1b", 0.6)
        ok("UI: Esc clears selection", "selected" not in scr.display[2], scr.display[2])
        t0 = re.findall(r"<title>(.*?)</title>", srv("/Playlist")); key(b"J")
        ok("UI: J moves the track down", wait(lambda: (lambda t: t != t0 and sorted(t) == sorted(t0))(re.findall(r"<title>(.*?)</title>", srv("/Playlist")))), srv("/Playlist")[:300])
        key(b"K"); ok("UI: K moves it back up", wait(lambda: re.findall(r"<title>(.*?)</title>", srv("/Playlist")) == t0), srv("/Playlist")[:300])
        key(b"\r"); ok("UI: Enter in queue plays that track", wait(lambda: status()["state"] == "play"), status())
        key(b"P"); ok("UI: P lists presets", wait(lambda: "1 Radio One" in scr.display[-1] and "2 Jazz & Blues" in scr.display[-1]), scr.display[-1])
        key(b"2"); ok("UI: 2 plays preset 2", wait(lambda: "Jazz & Blues" in scr.display[0]), scr.display[0])
        key(b"D"); ok("UI: D asks to clear", "Clear the whole queue" in text(), scr.display[-1])
        key(b"y"); ok("UI: y clears queue", wait(lambda: qlen() == 0) and wait(lambda: "Queue (0)" in text()), qlen())
        key(b"\t"); key(b"A"); ok("UI: A on album plays now", wait(lambda: qlen() > 0), qlen())
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 50, 0, 0)); scr.resize(12, 50); os.kill(pid, signal.SIGWINCH); pump(0.8)
        ok("UI: resize redraws", "Queue (" in scr.display[2], text())
        key(b"q", 1.0)
        code = None
        for _ in range(50):
            p, st = os.waitpid(pid, os.WNOHANG)
            if p: code = os.WEXITSTATUS(st) if os.WIFEXITED(st) else "signal %d" % os.WTERMSIG(st); break
            pump(0.1)
        else:
            os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0); code = "hung"
        ok("UI: q quits cleanly (exit 0, no sanitizer report)", code == 0 and not BAD.search(raw[0]), (code, BAD.search(raw[0])))
finally:
    fake.kill(); mdns.kill(); shutil.rmtree(TMP, ignore_errors=True)
print("\n%d/%d checks passed" % (total - fails, total))
sys.exit(1 if fails else 0)
