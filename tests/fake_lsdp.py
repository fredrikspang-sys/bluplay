#!/usr/bin/env python3
"""Tiny fake LSDP responder for testing bluplay's discovery without a network.

Listens on 127.0.0.1:PORT and answers any LSDP query with announce packets for the
players given on the command line. Point bluplay at it with BLUPLAY_LSDP_ADDR=127.0.0.1:PORT.

usage: fake_lsdp.py PORT "Name=ip:port" ...
"""
import socket, struct, sys

def field(data):
    if isinstance(data, str):
        data = data.encode()
    return bytes([len(data)]) + data

def announce(node_id, ip, name, port):
    header = bytes([6]) + b"LSDP" + bytes([1])
    body = field(node_id)
    body += field(socket.inet_aton(ip))
    body += bytes([1])  # one record: Player
    fields = [("name", name), ("port", str(port))]
    rec = struct.pack(">H", 1) + bytes([len(fields)])
    for k, v in fields:
        rec += field(k) + field(v)
    body += rec
    msg = bytes([2 + len(body), 0x41]) + body
    return header + msg

def main():
    port = int(sys.argv[1])
    players = []
    for i, spec in enumerate(sys.argv[2:]):
        nm, rest = spec.split("=", 1)
        ip, p = rest.rsplit(":", 1)
        players.append(announce(bytes([i + 1]), ip, nm, int(p)))
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", port))
    while True:
        data, addr = s.recvfrom(2048)
        if len(data) < 8 or data[1:5] != b"LSDP":
            continue
        for pkt in players:
            s.sendto(pkt, addr)

if __name__ == "__main__":
    main()
