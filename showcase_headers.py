"""Shows, request by request, how many header bytes each protocol puts on the wire."""
from common.site import BROWSER_HEADERS
from optihttp.frames import pack, HEADERS, END_STREAM
from optihttp.hpack_lite import HeaderTable, encode_block

enc = HeaderTable()
N = 40
print(f"{'request #':<12}{'HTTP/1.1 (bytes)':>20}{'OptiHTTP (bytes)':>20}")
tot1 = tot2 = 0
for i in range(1, N + 1):
    path = "/" if i == 1 else f"/img/photo{i}.png"
    lines = [f"GET {path} HTTP/1.1", "Host: localhost", "Connection: keep-alive"]
    lines += [f"{k.title()}: {v}" for k, v in BROWSER_HEADERS]
    if i > 1:
        lines.append("Referer: http://localhost/")
    h1 = len(("\r\n".join(lines) + "\r\n\r\n").encode())
    hd = [(":method", "GET"), (":path", path), (":scheme", "http"), (":authority", "localhost")] + BROWSER_HEADERS
    if i > 1:
        hd.append(("referer", "http://localhost/"))
    op = len(pack(HEADERS, END_STREAM, 2 * i - 1, b"\x03" + encode_block(enc, hd)))
    tot1 += h1
    tot2 += op
    if i <= 3 or i in (10, 40):
        print(f"{i:<12}{h1:>20,}{op:>20,}")
print(f"\nTotal for {N} requests: HTTP/1.1 = {tot1:,} B   OptiHTTP = {tot2:,} B   "
      f"({(1 - tot2 / tot1) * 100:.1f}% smaller)")
