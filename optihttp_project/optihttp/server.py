"""OptiHTTP server: one connection, many multiplexed streams, priority scheduling,
per-stream flow control, compressed headers."""
import asyncio
import email.utils
import struct
from collections import deque

from common.netem import shrink_send_buffer
from .frames import (DATA, HEADERS, WINDOW_UPDATE, END_STREAM, PREFACE, CHUNK,
                     INITIAL_WINDOW, pack, read_frame)
from .hpack_lite import HeaderTable, encode_block, decode_block
from common.site import response_meta


class _Stream:
    def __init__(self, sid, data, prio):
        self.sid, self.data, self.off, self.prio = sid, data, 0, prio
        self.window = INITIAL_WINDOW
        self.last = 0                      # round-robin tiebreak


class _Conn:
    def __init__(self, site, reader, writer):
        self.site, self.r, self.w = site, reader, writer
        self.enc, self.dec = HeaderTable(), HeaderTable()
        self.ctrl = deque()                # HEADERS frames, sent FIFO (keeps table in sync)
        self.streams = {}
        self.wake = asyncio.Event()
        self.tick = 0

    # ---- scheduler: strict priority, round-robin inside a priority level ----
    def _pick(self):
        ready = [s for s in self.streams.values() if s.off < len(s.data) and s.window > 0]
        return min(ready, key=lambda s: (s.prio, s.last)) if ready else None

    async def _writer_loop(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while True:
                if self.ctrl:
                    self.w.write(self.ctrl.popleft())
                    await self.w.drain()
                    continue
                s = self._pick()
                if s is None:
                    break
                n = min(CHUNK, s.window, len(s.data) - s.off)
                chunk = s.data[s.off:s.off + n]
                s.off += n
                s.window -= n
                self.tick += 1
                s.last = self.tick
                sid = s.sid
                end = s.off >= len(s.data)
                self.w.write(pack(DATA, END_STREAM if end else 0, sid, chunk))
                if end:
                    del self.streams[sid]
                await self.w.drain()

    async def run(self):
        writer_task = asyncio.create_task(self._writer_loop())
        try:
            while True:
                t, f, sid, payload = await read_frame(self.r)
                if t == HEADERS:
                    self._on_request(sid, payload)
                elif t == WINDOW_UPDATE:
                    s = self.streams.get(sid)
                    if s:
                        s.window += struct.unpack("!I", payload)[0]
                        self.wake.set()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer_task.cancel()
            self.w.close()

    def _on_request(self, sid, payload):
        prio = payload[0]
        req = dict(decode_block(self.dec, payload[1:]))
        res = self.site.get(req[":path"])
        date = email.utils.formatdate(usegmt=True)
        if res is None:
            block = encode_block(self.enc, [(":status", "404"), ("content-length", "0"),
                                            ("server", "DemoServer/1.0"), ("date", date)])
            self.ctrl.append(pack(HEADERS, END_STREAM, sid, block))
        else:
            meta, body = response_meta(res, "gzip" in req.get("accept-encoding", ""), date)
            block = encode_block(self.enc, [(":status", "200")] + meta)
            self.ctrl.append(pack(HEADERS, 0, sid, block))
            self.streams[sid] = _Stream(sid, body, prio)
        self.wake.set()


class OptiServer:
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
            if await r.readexactly(len(PREFACE)) != PREFACE:
                w.close()
                return
        except (asyncio.IncompleteReadError, ConnectionError):
            w.close()
            return
        await _Conn(self.site, r, w).run()
