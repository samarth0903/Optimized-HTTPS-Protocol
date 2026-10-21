import unittest
from optihttp.hpack_lite import HeaderTable, encode_block, decode_block
from common.site import BROWSER_HEADERS


class T(unittest.TestCase):
    def test_roundtrip_and_compression(self):
        enc, dec = HeaderTable(), HeaderTable()
        sizes = []
        for i in range(50):
            h = [(":method", "GET"), (":path", f"/img/p{i}.png"), (":scheme", "http"),
                 (":authority", "localhost")] + BROWSER_HEADERS
            blk = encode_block(enc, h)
            sizes.append(len(blk))
            self.assertEqual(decode_block(dec, blk), h)
        self.assertGreater(sizes[0], 400)       # first request: cookie etc. sent in full
        self.assertLess(sizes[10], 30)          # later requests: almost nothing

    def test_table_eviction_stays_in_sync(self):
        enc, dec = HeaderTable(256), HeaderTable(256)
        for i in range(100):
            h = [("x-k%d" % (i % 7), "v" * (10 + i % 30))]
            self.assertEqual(decode_block(dec, encode_block(enc, h)), h)


if __name__ == "__main__":
    unittest.main()
