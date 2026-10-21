"""Baseline: a faithful, plain HTTP/1.1 server and a browser-style client
(6 parallel keep-alive connections, one request at a time per connection)."""
import asyncio
import email.utils
import gzip
import time

from common.netem import shrink_send_buffer
from common.site import BROWSER_HEADERS, LINK_RE, response_meta


class H1Server:
    def __init__(self, site):
        self.site = site

    async def start(self, port=0):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        return self.server.sockets[0].getsockname()[1]

    def close(self):
        self.server.close()

    async def _handle(self, r, w):
        shrink_send_buffer(w)
        try:
            while True:
                head = await r.readuntil(b"\r\n\r\n")
                lines = head.decode("latin1").split("\r\n")
                _, path, _ = lines[0].split(" ")
                req = {k.lower(): v for k, v in (l.split(": ", 1) for l in lines[1:] if l)}
                res = self.site.get(path)
                date = email.utils.formatdate(usegmt=True)
                if res is None:
                    out = (f"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n"
                           f"Server: DemoServer/1.0\r\nDate: {date}\r\n\r\n").encode()
                else:
                    meta, body = response_meta(res, "gzip" in req.get("accept-encoding", ""), date)
                    h = "".join(f"{k.title()}: {v}\r\n" for k, v in meta)
                    out = (f"HTTP/1.1 200 OK\r\n{h}Connection: keep-alive\r\n\r\n").encode() + body
                w.write(out)
                await w.drain()
                if req.get("connection") == "close":
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()


class H1Conn:
    def __init__(self):
        self.req_header_bytes = 0

    async def open(self, port):
        self.r, self.w = await asyncio.open_connection("127.0.0.1", port)

    async def get(self, path):
        lines = [f"GET {path} HTTP/1.1", "Host: localhost", "Connection: keep-alive"]
        lines += [f"{k.title()}: {v}" for k, v in BROWSER_HEADERS]
        if path != "/":
            lines.append("Referer: http://localhost/")
        req = ("\r\n".join(lines) + "\r\n\r\n").encode()
        self.req_header_bytes += len(req)
        self.w.write(req)
        head = await self.r.readuntil(b"\r\n\r\n")
        hl = head.decode("latin1").split("\r\n")
        hdrs = {k.lower(): v for k, v in (l.split(": ", 1) for l in hl[1:] if l)}
        body = await self.r.readexactly(int(hdrs["content-length"]))
        if hdrs.get("content-encoding") == "gzip":
            body = gzip.decompress(body)
        return int(hl[0].split()[1]), hdrs, body

    def close(self):
        self.w.close()


async def load_page(port, max_conns=6):
    t0 = time.perf_counter()
    c0 = H1Conn()
    await c0.open(port)
    _, _, html = await c0.get("/")
    t_html = time.perf_counter() - t0
    paths = LINK_RE.findall(html.decode())
    q = asyncio.Queue()
    for p in paths:
        q.put_nowait(p)
    done, conns = {}, [c0]

    async def worker(conn):
        if conn is None:
            conn = H1Conn()
            conns.append(conn)
            await conn.open(port)
        while True:
            try:
                p = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            await conn.get(p)
            done[p] = time.perf_counter() - t0

    await asyncio.gather(worker(c0), *(worker(None) for _ in range(max_conns - 1)))
    total = time.perf_counter() - t0
    critical = max(done[p] for p in paths if p.endswith((".css", ".js")))
    hb = sum(c.req_header_bytes for c in conns)
    for c in conns:
        c.close()
    return {"total": total, "critical": critical, "html": t_html,
            "req_header_bytes": hb, "requests": len(paths) + 1}
