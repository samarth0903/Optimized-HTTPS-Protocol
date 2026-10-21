"""Tiny network emulator: a TCP proxy that adds latency and a shared bandwidth cap.

 * every new connection pays 1 RTT (models the TCP three-way handshake)
 * every byte pays RTT/2 one-way delay
 * all connections share ONE link per direction (like a real access link)
 * counts bytes and connections so we can report them
"""
import asyncio
import socket


def shrink_send_buffer(writer, size=16384):
    sock = writer.get_extra_info("socket")
    if sock is not None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, size)
    writer.transport.set_write_buffer_limits(high=size)


class NetEm:
    def __init__(self, target_port, rtt_ms, mbps):
        self.target = target_port
        self.rtt = rtt_ms / 1000
        self.oneway = self.rtt / 2
        self.bw = mbps * 1e6 / 8                 # bytes per second
        self.free = {"up": 0.0, "down": 0.0}     # when the shared link is next idle
        self.bytes = {"up": 0, "down": 0}
        self.conns = 0

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    def close(self):
        self.server.close()

    async def _handle(self, cr, cw):
        self.conns += 1
        await asyncio.sleep(self.rtt)            # TCP handshake
        loop = asyncio.get_running_loop()
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
        sock.setblocking(False)
        await loop.sock_connect(sock, ("127.0.0.1", self.target))
        sr, sw = await asyncio.open_connection(sock=sock)
        await asyncio.gather(self._pipe(cr, sw, "up"), self._pipe(sr, cw, "down"))

    async def _pipe(self, r, w, key):
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        async def sender():
            try:
                while True:
                    item = await q.get()
                    if item is None:
                        break
                    at, data = item
                    d = at - loop.time()
                    if d > 0:
                        await asyncio.sleep(d)
                    w.write(data)
                    await w.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                w.close()

        task = asyncio.create_task(sender())
        try:
            while True:
                data = await r.read(8192)
                if not data:
                    break
                self.bytes[key] += len(data)
                now = loop.time()
                start = max(now, self.free[key])
                done = start + len(data) / self.bw
                self.free[key] = done
                q.put_nowait((done + self.oneway, data))
                if start > now:                  # back-pressure: don't read ahead of the link
                    await asyncio.sleep(start - now)
        except (ConnectionError, OSError):
            pass
        finally:
            q.put_nowait(None)
            await task
