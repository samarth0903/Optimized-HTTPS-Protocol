import asyncio
import unittest
from common.site import build_site
from baseline.http11 import H1Server, H1Conn
from optihttp.server import OptiServer
from optihttp.client import OptiClient


class E2E(unittest.TestCase):
    def test_both_protocols_return_identical_bytes(self):
        async def go():
            site = build_site()
            h1, op = H1Server(site), OptiServer(site)
            p1, p2 = await h1.start(), await op.start()
            c1 = H1Conn(); await c1.open(p1)
            c2 = OptiClient(); await c2.connect(p2)
            paths = list(site) + ["/missing"]
            got2 = await asyncio.gather(*(c2.get(p) for p in paths))   # multiplexed, all at once
            for p, (st2, _, b2) in zip(paths, got2):
                st1, _, b1 = await c1.get(p)
                self.assertEqual(st1, st2)
                self.assertEqual(b1, b2)
                if p in site:
                    self.assertEqual(b2, site[p].body)
            c1.close(); await c2.close(); h1.close(); op.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
