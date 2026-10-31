#!/usr/bin/env python3
"""Minimal fake BluOS player for testing bluplay without real hardware.

Implements the subset of the BluOS HTTP API that bluplay uses (/Status with long-poll,
/SyncStatus, /Playlist, /Browse, /Add, /Play, /Pause, /Skip, /Back, /Volume, /Delete,
/Clear, /Reindex, /Stop, /Move, /Sleep, /Presets, /Preset, /Volume?mute) on 127.0.0.1, backed by a small invented music library.

usage: fake_player.py [PORT]            (default 11000)
env:   FAKE_QN=N    initial queue length (default 4)
       FAKE_LAT=MS  added latency per request (default 0)
       FAKE_LOG=F   log request paths to file F

Test-only control endpoint: /_x?resetq=N&song=I&state=play|pause|stop&vol=V
"""
import http.server, socketserver, urllib.parse as up, sys, time, os, random, hashlib, threading
from xml.sax.saxutils import escape, quoteattr as qa

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 11000
LAT = int(os.environ.get("FAKE_LAT", "0")) / 1000.0
LOG = open(os.environ["FAKE_LOG"], "w") if os.environ.get("FAKE_LOG") else None
COND = threading.Condition()
random.seed(1)

NAMES = ["Alpha", "alpha beta", "Bravo", "[Bracket]", "Charlie", "Æsir", "Øresund", "Åland", "Zulu", "zebra",
         "(c) Cee", "1984", "Delta", "Echo", "Foxtrot", "Golf", "Gamma", "Hotel", "india", "Juliet", "Kilo",
         "Lima", "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango", "Uniform"]
ALBUMS = [dict(n=n, a="Artist %d" % i, tracks=["%02d %s t%d" % (k + 1, n, k + 1) for k in range(random.randint(1, 6))])
          for i, n in enumerate(NAMES)]
MUSIC_ROOT = "/mnt/music"

def tfile(i, k): return "%s/%s/%s.flac" % (MUSIC_ROOT, ALBUMS[i]["n"], ALBUMS[i]["tracks"][k])
def make_queue(n): return [dict(t="Track %d" % (i + 1), a="Queue Artist", b="Queue Album", f="%s/queue/%02d.flac" % (MUSIC_ROOT, i + 1)) for i in range(n)]

Q = make_queue(int(os.environ.get("FAKE_QN", "4")))
S = {"state": "play", "vol": 40, "db": -40, "pid": 1, "song": 0, "base": 0.0, "t0": time.time(), "idx_t0": 0, "idx_dur": 0, "shuffle": 0, "repeat": 2, "mute": 0, "sleep": 0}
PRESETS = [dict(id=1, name="Radio One"), dict(id=2, name="Jazz & Blues")]   # /Presets, /Preset?id=N
SLEEPS = [15, 30, 45, 60, 90, 0]   # each /Sleep steps the timer
DELLOG = []

def secs(): return int(S["base"] + (time.time() - S["t0"] if S["state"] == "play" else 0))
def setpos(b=0.0): S["base"] = b; S["t0"] = time.time()
def bump():
    with COND: COND.notify_all()
def idxn():
    if not S["idx_dur"]: return 0
    e = time.time() - S["idx_t0"]
    return 0 if e >= S["idx_dur"] else 1 + int(e * 500)
def core():
    s = Q[S["song"]] if 0 <= S["song"] < len(Q) else None
    return ("<state>%s</state><pid>%d</pid><song>%d</song><title1>%s</title1><title2>%s</title2><title3>%s</title3>"
            "<volume>%d</volume><db>%d</db><totlen>200</totlen><indexing>%d</indexing><streamFormat>FLAC 16/44.1</streamFormat><shuffle>%d</shuffle><repeat>%d</repeat><mute>%d</mute>%s<sleep>%s</sleep>%s") % (
        S["state"], S["pid"], S["song"], escape(s["t"]) if s else "", escape(s["a"]) if s else "", escape(s["b"]) if s else "",
        S["vol"], S["db"], idxn(), S["shuffle"], S["repeat"], S["mute"], ("<muteDb>%d</muteDb>" % S["db"]) if S["mute"] else "",
        S["sleep"] or "", ("<fn>%s</fn>" % escape(s["f"])) if s else "")
def etag(c): return hashlib.md5(c.encode()).hexdigest()
def sect(n): return n[:1].upper() if n[:1].isalpha() and n[:1].isascii() else "#"
def aitem(i):
    a = ALBUMS[i]
    return '<item browseKey=%s contextMenuKey=%s playURL=%s text=%s text2=%s type="album"/>' % (
        qa("ALB:%d" % i), qa("CMA:%d" % i), qa("/Add?playnow=1&album=%d" % i), qa(a["n"]), qa(a["a"]))
def browse(k):
    if k == "LocalMusic:":
        return ('<browse serviceName="Library"><item browseKey="LocalMusic:bySection:Artist/x" text="Artists" type="link"/>'
                '<item browseKey="LocalMusic:bySection:Album/x" text="Albums" type="link"/></browse>')
    if k.startswith("LocalMusic:bySection:Album"):
        return '<browse serviceName="Library" type="sections">%s</browse>' % "".join(
            '<item browseKey=%s text=%s type="section"/>' % (qa("SEC:" + c), qa(c)) for c in sorted(set(sect(a["n"]) for a in ALBUMS)))
    if k.startswith("LocalMusic:bySection:Artist"):
        return '<browse serviceName="Library">%s</browse>' % "".join(
            '<item browseKey=%s text=%s type="artist"/>' % (qa("ART:%d" % i), qa(a["a"])) for i, a in enumerate(ALBUMS))
    if k.startswith("ART:"):
        return '<browse serviceName="Library">%s</browse>' % aitem(int(k[4:]))
    if k.startswith("SEC:") or k.startswith("NEXT:"):   # sections paged 3 at a time (exercises nextKey)
        if k.startswith("SEC:"): c, off = k[4:], 0
        else: _, c, off = k.split(":", 2); off = int(off)
        idx = [i for i, a in enumerate(ALBUMS) if sect(a["n"]) == c][off:]
        nk = (' nextKey=%s' % qa("NEXT:%s:%d" % (c, off + 3))) if len(idx) > 3 else ""
        return '<browse serviceName="Library"%s>%s</browse>' % (nk, "".join(aitem(i) for i in idx[:3]))
    if k.startswith("ALB:"):
        i = int(k[4:]); a = ALBUMS[i]
        return '<browse serviceName=%s>%s</browse>' % (qa(a["n"]), "".join(
            '<item text=%s type="track" playURL=%s contextMenuKey=%s/>' % (qa(t), qa("/Add?playnow=1&file=" + up.quote(tfile(i, j))), qa("CMT:%d:%d" % (i, j)))
            for j, t in enumerate(a["tracks"])))
    if k.startswith("CMA:"):
        return '<browse type="contextMenu"><item actionURL="/Add?playnow=-1&amp;where=last&amp;album=%d" type="addAll-last" text="Add all"/></browse>' % int(k[4:])
    if k.startswith("CMT:"):
        _, i, j = k.split(":")
        return '<browse type="contextMenu"><item actionURL="/Add?playnow=-1&amp;where=last&amp;file=%s" type="add-last" text="Add last"/></browse>' % escape(up.quote(tfile(int(i), int(j))))
    return '<browse serviceName="?"></browse>'

GRP = set()   # (ip, port) of grouped players (AddSlave/RemoveSlave)
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        if LOG: LOG.write(self.path + "\n"); LOG.flush()
        if LAT: time.sleep(LAT)
        u = up.urlparse(self.path); p = u.path; qs = up.parse_qs(u.query, keep_blank_values=True)
        g = lambda k, d=None: qs.get(k, [d])[0]
        x = ""
        if p == "/SyncStatus": x = '<SyncStatus name="Fake Player" modelName="FAKE">%s</SyncStatus>' % "".join('<slave id="%s" port="%s"/>' % s for s in sorted(GRP))
        elif p in ("/AddSlave", "/RemoveSlave"):
            (GRP.add if p == "/AddSlave" else GRP.discard)((g("slave"), g("port", "11000"))); x = '<addSlave/>'
        elif p == "/Status":
            tmo = float(g("timeout", "0")); et = g("etag"); end = time.time() + tmo
            while et and tmo:
                with COND:
                    if etag(core()) != et or time.time() >= end: break
                    COND.wait(min(0.2, max(0.01, end - time.time())))
            c = core(); x = '<status etag="%s">%s<secs>%d</secs></status>' % (etag(c), c, secs())
        elif p == "/_x":
            if "resetq" in qs: Q[:] = make_queue(int(g("resetq"))); S["pid"] += 1; DELLOG.clear()
            if "song" in qs: S["song"] = int(g("song")); setpos(0)
            if "state" in qs: setpos(secs()); S["state"] = g("state")
            if "vol" in qs: S["vol"] = int(g("vol")); S["db"] = S["vol"] - 80
            if "dellog" in qs: x = "<dellog>%s</dellog>" % "".join('<id id="%d"/>' % i for i in DELLOG)
            bump(); x = x or "<ok/>"
        elif p == "/Reindex":
            if idxn() == 0: S["idx_t0"] = time.time(); S["idx_dur"] = float(os.environ.get("FAKE_IDX_SECS", "3"))
            x = "<indexing>%d</indexing>" % idxn()
        elif p == "/Playlist":
            x = '<playlist length="%d" id="%d">%s</playlist>' % (len(Q), S["pid"], "".join(
                '<song id="%d"><art>%s</art><alb>%s</alb><title>%s</title><fn>%s</fn></song>' % (i, escape(s["a"]), escape(s["b"]), escape(s["t"]), escape(s["f"]))
                for i, s in enumerate(Q)))
        elif p == "/Delete":
            i = int(g("id", "-1")); DELLOG.append(i)
            if 0 <= i < len(Q):
                del Q[i]; S["pid"] += 1
                if i < S["song"]: S["song"] -= 1
            bump(); x = "<deleted>%d</deleted>" % i
        elif p == "/Add":
            if "file" in qs:
                f = g("file"); Q.append(dict(t=os.path.splitext(os.path.basename(f))[0], a="Added Artist", b="Added Album", f=f))
            elif "album" in qs:
                i = int(g("album"))
                for j, t in enumerate(ALBUMS[i]["tracks"]): Q.append(dict(t=t, a=ALBUMS[i]["a"], b=ALBUMS[i]["n"], f=tfile(i, j)))
            if g("playnow") == "1": S["song"] = len(Q) - 1; S["state"] = "play"; setpos(0)
            S["pid"] += 1; bump(); x = "<addsong/>"
        elif p == "/Play":
            if "seek" in qs: setpos(float(g("seek")))
            elif "id" in qs: S["song"] = int(g("id")); setpos(0)
            else: setpos(secs())
            S["state"] = "play"; bump(); x = "<state>play</state>"
        elif p == "/Clear": Q.clear(); S["pid"] += 1; S["song"] = -1; bump(); x = "<playlist/>"
        elif p == "/Browse": x = browse(g("key", "LocalMusic:"))
        elif p == "/Volume" and "mute" not in qs:
            if "db" in qs: S["db"] = max(-80, min(0, S["db"] + int(g("db")))); S["vol"] = S["db"] + 80
            bump(); x = '<volume db="%d">%d</volume>' % (S["db"], S["vol"])
        elif p == "/Volume" and "mute" in qs:   # real player: level kept, reply db="-100" mute="1" muteDb=..
            S["mute"] = int(g("mute")); bump(); x = '<volume db="%d" mute="%d">%d</volume>' % (-100 if S["mute"] else S["db"], S["mute"], 0 if S["mute"] else S["vol"])
        elif p == "/Stop": setpos(0); S["state"] = "stop"; bump(); x = "<state>stop</state>"
        elif p == "/Sleep":
            S["sleep"] = SLEEPS[(SLEEPS.index(S["sleep"]) + 1) % len(SLEEPS)]; bump(); x = "<sleep>%s</sleep>" % (S["sleep"] or "")
        elif p == "/Move":   # 0-based song ids, as on the real player (verified: Move?old=0&new=1 swapped rows 0 and 1, playlist id +1)
            o, n = int(g("old")), int(g("new")); Q.insert(n, Q.pop(o)); S["pid"] += 1
            if S["song"] == o: S["song"] = n
            elif o < S["song"] <= n: S["song"] -= 1
            elif n <= S["song"] < o: S["song"] += 1
            bump(); x = "<moved>moved</moved>"
        elif p == "/Presets": x = '<presets prid="0">%s</presets>' % "".join('<preset id="%d" name=%s url="x"/>' % (q["id"], qa(q["name"])) for q in PRESETS)
        elif p == "/Preset":
            q = [q for q in PRESETS if q["id"] == int(g("id", "0"))]
            if q: Q[:] = [dict(t=q[0]["name"], a="Preset", b="Radio", f="")]; S["pid"] += 1; S["song"] = 0; S["state"] = "play"; setpos(0)
            bump(); x = "<state>play</state>"
        elif p in ("/Shuffle", "/Repeat"):
            k = p[1:].lower(); S[k] = int(g("state", "0")); bump(); x = '<playlist shuffle="%d" repeat="%d"/>' % (S["shuffle"], S["repeat"])
        elif p == "/Pause":
            setpos(secs()); S["state"] = "pause" if S["state"] == "play" else "play"; bump(); x = "<state>%s</state>" % S["state"]
        elif p == "/Skip":
            if Q: S["song"] = (S["song"] + 1) % len(Q)
            setpos(0); bump(); x = "<id>%d</id>" % S["song"]
        elif p == "/Back": setpos(0); bump(); x = "<id>%d</id>" % S["song"]
        else:
            self.send_response(404); self.end_headers(); return
        b = ('<?xml version="1.0" encoding="UTF-8"?>' + x).encode()
        self.send_response(200); self.send_header("Content-Type", "text/xml"); self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

class T(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True

if __name__ == "__main__":
    T(("127.0.0.1", PORT), H).serve_forever()
