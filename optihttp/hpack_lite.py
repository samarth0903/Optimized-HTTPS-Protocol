"""Header compression for OptiHTTP (HPACK-inspired, no Huffman coding).

Idea: both sides keep an identical table of recently seen (name, value) pairs.
A header that is already in the table is sent as a 1-2 byte index instead of
as text.  Headers like cookie / user-agent / accept-* repeat on every request,
so after the first request they cost almost nothing.
"""
from itertools import chain

STATIC = [
    (":method", "GET"), (":method", "POST"), (":path", "/"), (":scheme", "http"),
    (":status", "200"), (":status", "404"), (":authority", "localhost"),
    ("accept", "*/*"), ("accept-encoding", "gzip"), ("accept-language", ""),
    ("user-agent", ""), ("cookie", ""), ("referer", ""),
    ("content-type", "text/html"), ("content-type", "text/css"),
    ("content-type", "application/javascript"), ("content-type", "image/png"),
    ("content-type", "application/json"), ("content-encoding", "gzip"),
    ("content-length", ""), ("cache-control", ""), ("etag", ""),
    ("server", ""), ("date", ""),
]
# Values that are unique per request: indexing them would only evict useful entries.
NEVER_INDEX = {":path", "etag", "content-length"}


def _enc_int(value, prefix_bits, flags):
    maxp = (1 << prefix_bits) - 1
    if value < maxp:
        return bytes([flags | value])
    out = [flags | maxp]
    value -= maxp
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def _dec_int(buf, pos, prefix_bits):
    maxp = (1 << prefix_bits) - 1
    v = buf[pos] & maxp
    pos += 1
    if v < maxp:
        return v, pos
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        v += (b & 127) << shift
        shift += 7
        if not b & 128:
            return v, pos


def _enc_str(s):
    raw = s.encode("utf-8")
    return _enc_int(len(raw), 7, 0) + raw


def _dec_str(buf, pos):
    n, pos = _dec_int(buf, pos, 7)
    return buf[pos:pos + n].decode("utf-8"), pos + n


class HeaderTable:
    """Static table + FIFO dynamic table, bounded by max_size bytes."""

    def __init__(self, max_size=4096):
        self.dyn = []          # newest first
        self.size = 0
        self.max_size = max_size

    @staticmethod
    def _cost(n, v):
        return len(n) + len(v) + 32

    def add(self, name, value):
        c = self._cost(name, value)
        if c > self.max_size:
            self.dyn.clear()
            self.size = 0
            return
        while self.size + c > self.max_size:
            n, v = self.dyn.pop()
            self.size -= self._cost(n, v)
        self.dyn.insert(0, (name, value))
        self.size += c

    def get(self, idx):
        if idx <= len(STATIC):
            return STATIC[idx - 1]
        return self.dyn[idx - len(STATIC) - 1]

    def find(self, name, value):
        """Return (index of exact match or 0, index of a same-name entry or 0)."""
        name_idx = 0
        for i, (n, v) in enumerate(chain(STATIC, self.dyn), 1):
            if n == name:
                name_idx = name_idx or i
                if v == value:
                    return i, name_idx
        return 0, name_idx


def encode_block(table, headers):
    out = bytearray()
    for name, value in headers:
        full, name_idx = table.find(name, value)
        if full:
            out += _enc_int(full, 7, 0x80)                      # indexed header
            continue
        index_it = name not in NEVER_INDEX
        out += _enc_int(name_idx, 6, 0x40 if index_it else 0x00)  # literal header
        if not name_idx:
            out += _enc_str(name)
        out += _enc_str(value)
        if index_it:
            table.add(name, value)
    return bytes(out)


def decode_block(table, data):
    pos, out = 0, []
    while pos < len(data):
        b = data[pos]
        if b & 0x80:
            idx, pos = _dec_int(data, pos, 7)
            out.append(table.get(idx))
            continue
        index_it = bool(b & 0x40)
        idx, pos = _dec_int(data, pos, 6)
        if idx:
            name = table.get(idx)[0]
        else:
            name, pos = _dec_str(data, pos)
        value, pos = _dec_str(data, pos)
        if index_it:
            table.add(name, value)
        out.append((name, value))
    return out
