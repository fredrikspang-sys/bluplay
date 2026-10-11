#!/usr/bin/env python3
"""Tiny fake mDNS responder for testing bluplay's discovery without a network.

Listens on 127.0.0.1:PORT (not the real 5353 multicast group) and answers any query with
PTR/SRV/A records for the players given on the command line. Point bluplay at it with
BLUPLAY_MDNS_ADDR=127.0.0.1:PORT.

usage: fake_mdns.py PORT "Name=ip:port[/service]" ...     (service default _musc)
"""
import socket, struct, sys

def name(n):
    out = b""
    for lab in n.rstrip(".").split("."):
        b = lab.encode(); out += bytes([len(b)]) + b
    return out + b"\0"
def rr(owner, typ, rdata, ttl=120):
    return name(owner) + struct.pack(">HHIH", typ, 0x8001, ttl, len(rdata)) + rdata

def main():
    port = int(sys.argv[1]); players = []
    for spec in sys.argv[2:]:
        nm, rest = spec.split("=", 1)
        svc = "_musc"
        if "/" in rest: rest, svc = rest.split("/", 1)
        ip, p = rest.rsplit(":", 1); players.append((nm, ip, int(p), svc))
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", port))
    while True:
        data, addr = s.recvfrom(9000)
        if len(data) < 12: continue
        qid = data[:2]; recs = []
        for i, (nm, ip, p, svc) in enumerate(players):
            stype = "%s._tcp.local" % svc; inst = "%s.%s" % (nm, stype); host = "fakeplayer%d.local" % i
            recs.append(rr(stype, 12, name(inst)))
            recs.append(rr(inst, 33, struct.pack(">HHH", 0, 0, p) + name(host)))
            recs.append(rr(host, 1, socket.inet_aton(ip)))
        hdr = qid + struct.pack(">HHHHH", 0x8400, 0, len(recs), 0, 0)
        s.sendto(hdr + b"".join(recs), addr)

if __name__ == "__main__":
    main()
