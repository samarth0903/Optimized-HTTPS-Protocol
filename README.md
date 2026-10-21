# OptiHTTP — an optimised HTTP, implemented and benchmarked against HTTP/1.1

A working application-layer protocol (Python 3.9+, standard library only) that fixes the main
performance flaws of HTTP/1.1, plus a harness that **proves** the improvement on the same website
under emulated networks.

## 1. Flaws of HTTP/1.1 → what OptiHTTP does

| # | HTTP/1.1 flaw | Effect | OptiHTTP fix | Where |
|---|---|---|---|---|
| 1 | Text headers repeated on every request (cookie, user-agent…) | ~700 B per request, ~93 % redundant | Header compression with a shared static + dynamic table (HPACK-style) | `optihttp/hpack_lite.py` |
| 2 | One request at a time per connection (head-of-line blocking at HTTP level) | Browsers need 6 parallel connections | Multiplexed **streams** over one connection | `optihttp/frames.py`, `client.py` |
| 3 | Many TCP connections | 1 RTT handshake each, slow-start each | One persistent connection | `optihttp/client.py` |
| 4 | No prioritisation | Big images compete with CSS/JS that block rendering | 1-byte priority per request; server uses strict priority + round-robin scheduler | `optihttp/server.py` |
| 5 | No flow control per resource | One big download can starve others | Per-stream window + WINDOW_UPDATE frames | `server.py`, `client.py` |
| 6 | Text parsing is slow/ambiguous | Parsing bugs, request smuggling | Fixed-size binary frame header | `optihttp/frames.py` |

## 2. Wire format

```
+---------+------+-------+-----------+----------------+
| len(2B) | type | flags | stream(4) | payload (len)  |
+---------+------+-------+-----------+----------------+
type: 0 DATA  1 HEADERS  2 WINDOW_UPDATE        flags: 0x1 END_STREAM
Request HEADERS payload  = priority(1B) + compressed header block
Response HEADERS payload = compressed header block
Connection starts with the preface  b"OPTIHTTP/1\r\n"
```
Header block entries: `1xxxxxxx` = indexed (7-bit int), `01xxxxxx` = literal + add to table,
`00xxxxxx` = literal, never indexed (unique values such as `:path`, `etag`, `content-length`).

## 3. Project layout

```
optihttp/     the new protocol: frames, header compression, server, client
baseline/     faithful HTTP/1.1 server + browser-style client (6 keep-alive connections)
common/       demo site (shared by both!), network emulator (latency + shared bandwidth)
bench.py      runs both protocols on 3 network profiles -> results.json, report.html
showcase_headers.py   request-by-request header-size comparison
tests/        header-compression round trip, end-to-end byte-identical check
```

## 4. Run it

```bash
python showcase_headers.py          # header bytes: HTTP/1.1 vs OptiHTTP
python bench.py                     # full benchmark (add a number for more runs, e.g. 5)
open report.html                    # visual comparison
python -m unittest discover -s tests -t .
```

## 5. Results (median of 5 runs; page = 1 HTML + 3 CSS + 5 JS + 24 images + 12 API calls)

| Network | Metric | HTTP/1.1 | OptiHTTP | Change |
|---|---|---|---|---|
| Fibre (10 ms, 100 Mbps) | Page loaded | 0.15 s | 0.11 s | -29 % |
| | Render-critical (HTML+CSS+JS) | 0.06 s | 0.04 s | -30 % |
| 4G (60 ms, 20 Mbps) | Page loaded | 0.80 s | 0.50 s | -37 % |
| | Render-critical | 0.32 s | 0.21 s | -33 % |
| Slow mobile (150 ms, 5 Mbps) | Page loaded | 2.27 s | 1.72 s | -24 % |
| | Render-critical | 0.79 s | 0.55 s | -30 % |
| all | Request bytes sent | 31,368 B | 2,267 B | -93 % |
| all | TCP connections | 6 | 1 | -83 % |

**Why these numbers:** latency-bound networks gain most (one connection removes the extra
handshake RTT, and all requests leave at once). On slow links, total time is dominated by the
~1 MB of image payload, which no protocol can shrink, so the gain there is smaller, but
the priority scheduler still delivers the render-critical files ~30 % sooner.
Header compression saves 93 % of upstream bytes regardless of network.

## 6. Honest limitations (good to state in your report)

* Both protocols run over TCP, so **TCP-level head-of-line blocking remains** under packet loss.
  Fixing it needs a UDP/QUIC transport (that is what HTTP/3 does) — listed as future work.
* TCP slow-start and packet loss are not modelled by the emulator; latency, bandwidth and
  handshake cost are.
* Compression (gzip) is enabled identically on both protocols so the gains shown are
  from the protocol itself, not from a feature only one side has.
* No TLS: add `ssl.SSLContext` to `asyncio.start_server/open_connection` for encryption.
* The emulator runs on localhost; absolute times will differ on a real network, the relative
  trend is what matters.
* OptiHTTP is inspired by HTTP/2 (HPACK, streams, priorities, flow control); the design and
  all code here are written from scratch for this assignment.

## 7. Ideas to extend

Connection-level flow control · server push of critical resources · dynamic priority
(re-prioritise on scroll) · Huffman coding for header strings · TLS · a QUIC/UDP transport.
