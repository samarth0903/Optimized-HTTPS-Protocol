"""Benchmark: HTTP/1.1 vs OptiHTTP on the same site, over emulated networks.
Usage:  python bench.py [runs]        (default 3 runs per cell, median reported)
Writes: results.json, report.html
"""
import asyncio
import json
import statistics
import sys

from common.site import build_site
from common.netem import NetEm
from baseline import http11
from optihttp import client as opti_client
from optihttp.server import OptiServer

PROFILES = [("Fibre", 10, 100), ("4G", 60, 20), ("Slow mobile", 150, 5)]   # name, RTT ms, Mbps
PROTOS = ["HTTP/1.1", "OptiHTTP"]


async def run_once(proto, rtt, mbps, ports):
    em = NetEm(ports[proto], rtt, mbps)
    port = await em.start()
    loader = http11.load_page if proto == "HTTP/1.1" else opti_client.load_page
    r = await loader(port)
    await asyncio.sleep(0.05)
    r.update(up=em.bytes["up"], down=em.bytes["down"], conns=em.conns)
    em.close()
    return r


def median(runs, key):
    return statistics.median(r[key] for r in runs)


async def main(runs):
    site = build_site()
    h1, op = http11.H1Server(site), OptiServer(site)
    ports = {"HTTP/1.1": await h1.start(), "OptiHTTP": await op.start()}
    results = []
    for name, rtt, mbps in PROFILES:
        row = {"profile": name, "rtt": rtt, "mbps": mbps}
        for proto in PROTOS:
            rs = [await run_once(proto, rtt, mbps, ports) for _ in range(runs)]
            row[proto] = {k: median(rs, k) for k in
                          ("total", "critical", "html", "up", "down", "conns",
                           "req_header_bytes", "requests")}
        results.append(row)
        print(f"  finished profile {name}", flush=True)
    h1.close()
    op.close()
    return results


def print_table(results):
    print(f"\n{'Network':<26}{'Metric':<24}{'HTTP/1.1':>12}{'OptiHTTP':>12}{'Change':>10}")
    print("-" * 84)
    metrics = [("Page fully loaded (s)", "total", 1, "{:.2f}"),
               ("Render-critical done (s)", "critical", 1, "{:.2f}"),
               ("Request bytes sent", "up", 1, "{:,.0f}"),
               ("Request header bytes", "req_header_bytes", 1, "{:,.0f}"),
               ("TCP connections", "conns", 1, "{:.0f}")]
    for row in results:
        label = f"{row['profile']} ({row['rtt']}ms, {row['mbps']}Mbps)"
        for i, (title, key, _, fmt) in enumerate(metrics):
            a, b = row["HTTP/1.1"][key], row["OptiHTTP"][key]
            chg = f"{(b - a) / a * 100:+.0f}%"
            print(f"{label if i == 0 else '':<26}{title:<24}{fmt.format(a):>12}{fmt.format(b):>12}{chg:>10}")
        print()


def write_report(results):
    metrics = [("Page fully loaded", "total", "s", 2), ("Render-critical resources ready", "critical", "s", 2),
               ("Bytes sent client\u2192server", "up", " B", 0), ("TCP connections", "conns", "", 0)]
    cards = []
    for row in results:
        rows = []
        for title, key, unit, dp in metrics:
            a, b = row["HTTP/1.1"][key], row["OptiHTTP"][key]
            mx = max(a, b)
            rows.append(f"""<div class="m"><div class="t">{title}</div>
<div class="bar"><span class="l">HTTP/1.1</span><i class="a" style="width:{a/mx*100:.1f}%"></i><b>{a:,.{dp}f}{unit}</b></div>
<div class="bar"><span class="l">OptiHTTP</span><i class="b" style="width:{b/mx*100:.1f}%"></i><b>{b:,.{dp}f}{unit}</b></div>
<div class="d">{(b-a)/a*100:+.0f}%</div></div>""")
        cards.append(f'<section><h2>{row["profile"]} <small>RTT {row["rtt"]} ms \u00b7 {row["mbps"]} Mbps</small></h2>{"".join(rows)}</section>')
    html = f"""<!doctype html><meta charset="utf-8"><title>OptiHTTP vs HTTP/1.1</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--a:#c0504d;--b:#2e8b57;--card:#f5f5f5}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#eee;--mut:#999;--card:#22252b}}}}
body{{font:15px system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:820px;margin:2rem auto;padding:0 1rem}}
section{{background:var(--card);border-radius:12px;padding:1rem 1.2rem;margin:1rem 0}}
h2 small{{color:var(--mut);font-weight:400;font-size:.7em}}
.m{{margin:.9rem 0}} .t{{font-weight:600;margin-bottom:.3rem}}
.bar{{display:flex;align-items:center;gap:.5rem;margin:.15rem 0}}
.l{{width:70px;color:var(--mut);font-size:.85em}}
.bar i{{display:block;height:14px;border-radius:3px;min-width:2px}} .a{{background:var(--a)}} .b{{background:var(--b)}}
.bar b{{font-size:.85em;font-weight:500}} .d{{color:var(--b);font-weight:700;text-align:right}}
</style>
<h1>OptiHTTP vs HTTP/1.1</h1>
<p>Same site (1 HTML, 3 CSS, 5 JS, 24 images, 12 API calls), same server logic, emulated network. Median of runs. Lower is better.</p>
{"".join(cards)}"""
    open("report.html", "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"Benchmarking ({runs} runs per cell)...")
    res = asyncio.run(main(runs))
    print_table(res)
    json.dump(res, open("results.json", "w"), indent=2)
    write_report(res)
    print("Wrote results.json and report.html")
