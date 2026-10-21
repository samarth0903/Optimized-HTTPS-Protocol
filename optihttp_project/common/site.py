"""A deterministic demo website used by BOTH servers, so the comparison is fair."""
import gzip
import random
import hashlib
import re

TEXT_TYPES = {"text/html", "text/css", "application/javascript", "application/json"}
PRIORITY = {"text/html": 0, "text/css": 1, "application/javascript": 1,
            "application/json": 2, "image/png": 3}
LINK_RE = re.compile(r'(?:href|src|data-api)="([^"]+)"')

_rng = random.Random(1234)
_COOKIE = "; ".join([
    "session=" + _rng.randbytes(96).hex(),
    "_ga=GA1.2." + str(_rng.randint(10**8, 10**9)) + ".1700000000",
    "theme=dark", "cart=" + _rng.randbytes(40).hex(),
    "csrftoken=" + _rng.randbytes(32).hex()])

# Headers a real browser sends with every single request
BROWSER_HEADERS = [
    ("user-agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    ("accept", "*/*"),
    ("accept-encoding", "gzip"),
    ("accept-language", "en-US,en;q=0.9"),
    ("cookie", _COOKIE),
]


class Resource:
    def __init__(self, path, ctype, body):
        self.path, self.ctype, self.body = path, ctype, body
        self.gz = gzip.compress(body, 6, mtime=0) if ctype in TEXT_TYPES else None
        self.etag = '"' + hashlib.md5(body).hexdigest()[:16] + '"'
        self.prio = PRIORITY[ctype]


def priority_for(path):
    if path == "/":
        return 0
    if path.endswith((".css", ".js")):
        return 1
    if path.endswith(".json"):
        return 2
    return 3


def _text(rng, n, words):
    out, size = [], 0
    while size < n:
        w = rng.choice(words)
        out.append(w)
        size += len(w) + 1
    return " ".join(out).encode()[:n]


def build_site(seed=7):
    rng = random.Random(seed)
    words = ("function return const var let class margin padding display flex grid color "
             "background border width height value data item list render state update "
             "props event handler click style layout header footer content").split()
    css = [f"/css/app{i}.css" for i in range(3)]
    js = [f"/js/chunk{i}.js" for i in range(5)]
    imgs = [f"/img/photo{i}.png" for i in range(24)]
    api = [f"/api/item{i}.json" for i in range(12)]
    res = {}

    def add(path, ctype, body):
        res[path] = Resource(path, ctype, body)

    for p in css:
        add(p, "text/css", _text(rng, 30_000, words))
    for p in js:
        add(p, "application/javascript", _text(rng, 40_000, words))
    for p in imgs:
        add(p, "image/png", rng.randbytes(rng.randint(8_000, 60_000)))   # incompressible
    for p in api:
        add(p, "application/json", ('{"items":[' + ",".join(
            f'{{"id":{rng.randint(1, 10**6)},"name":"{rng.choice(words)}"}}'
            for _ in range(60)) + "]}").encode())
    html = ["<!doctype html><html><head><title>Demo</title>"]
    html += [f'<link rel="stylesheet" href="{p}">' for p in css]
    html += [f'<script src="{p}"></script>' for p in js]
    html += ["</head><body><h1>Gallery</h1>"]
    html += [f'<img src="{p}">' for p in imgs]
    html += [f'<div data-api="{p}"></div>' for p in api]
    html.append("<p>" + _text(rng, 4000, words).decode() + "</p></body></html>")
    add("/", "text/html", "".join(html).encode())
    return res


def response_meta(r, accepts_gzip, date):
    """Shared response logic -> (list of headers, body bytes)."""
    use_gz = accepts_gzip and r.gz is not None
    body = r.gz if use_gz else r.body
    hdrs = [("content-type", r.ctype)]
    if use_gz:
        hdrs.append(("content-encoding", "gzip"))
    hdrs += [("content-length", str(len(body))),
             ("cache-control", "public, max-age=3600"),
             ("etag", r.etag), ("server", "DemoServer/1.0"), ("date", date)]
    return hdrs, body
