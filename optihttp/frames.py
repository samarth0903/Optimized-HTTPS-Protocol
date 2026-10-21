"""OptiHTTP binary framing.

    +---------+------+-------+-----------+----------------+
    | len(2B) | type | flags | stream(4) | payload (len)  |
    +---------+------+-------+-----------+----------------+

Request  HEADERS payload = [priority(1B)] + compressed header block
Response HEADERS payload = compressed header block
"""
import struct

_HDR = struct.Struct("!HBBI")
DATA, HEADERS, WINDOW_UPDATE = 0, 1, 2
END_STREAM = 0x1
PREFACE = b"OPTIHTTP/1\r\n"
CHUNK = 4096                  # max DATA payload per frame (keeps scheduling fine-grained)
INITIAL_WINDOW = 65535        # per-stream flow-control window
FRAME_OVERHEAD = _HDR.size


def pack(ftype, flags, stream_id, payload=b""):
    return _HDR.pack(len(payload), ftype, flags, stream_id) + payload


async def read_frame(reader):
    ln, t, f, sid = _HDR.unpack(await reader.readexactly(_HDR.size))
    payload = await reader.readexactly(ln) if ln else b""
    return t, f, sid, payload
