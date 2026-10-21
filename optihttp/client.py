"""OptiHTTP client: ONE connection, all requests in flight at once."""
import asyncio
import gzip
import struct
import time

from common.site import BROWSER_HEADERS, LINK_RE, priority_for
from .frames import (DATA, HEADERS, WINDOW_UPDATE, END_STREAM, PREFACE, pack, read_frame)
from .hpack_lite import HeaderTable, encode_block, decode_block

ACK_EVERY = 32768


class _Pending:
    def __init__(self, fut):
        self.fut, self.headers, self.chunks, self.unacked = fut, {}, [], 0


class OptiClient:
    async def connect(self, port):
        self.r, self.w = await asyncio.open_connection("127.0.0.1", port)
        self.w.write(PREFACE)
        self.enc, self.dec = HeaderTable(), HeaderTable()
        self.next_id, self.pending = 1, {}
        self.req_header_bytes = 0
        self._task = asyncio.create_task(self._read_loop())

    async def close(self):
        self._task.cancel()
        self.w.close()

    async def get(self, path, prio=3):
        sid = self.next_id
        self.next_id += 2
        fut = asyncio.get_running_loop().create_future()
        self.pending[sid] = _Pending(fut)
        hdrs = [(":method", "GET"), (":path", path), (":scheme", "http"),
                (":authority", "localhost")] + BROWSER_HEADERS
        if path != "/":
            hdrs.append(("referer", "http://localhost/"))
        block = encode_block(self.enc, hdrs)
        frame = pack(HEADERS, END_STREAM, sid, bytes([prio]) + block)
        self.req_header_bytes += len(frame)
        self.w.write(frame)
        return await fut

    async def _read_loop(self):
        try:
            while True:
                t, f, sid, payload = await read_frame(self.r)
                p = self.pending[sid]
                if t == HEADERS:
                    p.headers = dict(decode_block(self.dec, payload))
                elif t == DATA:
                    p.chunks.append(payload)
                    p.unacked += len(payload)
                    if p.unacked >= ACK_EVERY and not f & END_STREAM:
                        self.w.write(pack(WINDOW_UPDATE, 0, sid, struct.pack("!I", p.unacked)))
                        p.unacked = 0
                if f & END_STREAM:
                    body = b"".join(p.chunks)
                    if p.headers.get("content-encoding") == "gzip":
                        body = gzip.decompress(body)
                    del self.pending[sid]
                    p.fut.set_result((int(p.headers[":status"]), p.headers, body))
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass


async def load_page(port):
    """Load '/', discover sub-resources, fetch them ALL immediately with priorities."""
    t0 = time.perf_counter()
    c = OptiClient()
    await c.connect(port)
    _, _, html = await c.get("/", prio=0)
    t_html = time.perf_counter() - t0
    paths = LINK_RE.findall(html.decode())
    done = {}

    async def fetch(p):
        await c.get(p, prio=priority_for(p))
        done[p] = time.perf_counter() - t0

    await asyncio.gather(*(fetch(p) for p in paths))
    total = time.perf_counter() - t0
    critical = max(done[p] for p in paths if p.endswith((".css", ".js")))
    await c.close()
    return {"total": total, "critical": critical, "html": t_html,
            "req_header_bytes": c.req_header_bytes, "requests": len(paths) + 1}
