import tempfile
import unittest
from pathlib import Path

import pandas as pd

from contest_trade.utils.cache_io import read_cache, write_cache


class CacheIOTests(unittest.TestCase):
    def test_round_trips_dataframe_without_pickle(self):
        frame = pd.DataFrame(
            {
                "symbol": ["600519.SH", "000001.SZ"],
                "value": [1.5, 2.5],
                "time": pd.to_datetime(["2026-07-25", "2026-07-26"]),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.json.gz"
            write_cache(path, frame)
            restored = read_cache(path)

        pd.testing.assert_frame_equal(restored, frame)

    def test_round_trips_json_value(self):
        value = {"ok": True, "items": [1, 2, 3]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json.gz"
            write_cache(path, value)
            restored = read_cache(path)

        self.assertEqual(restored, value)

    def test_rejects_unknown_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json.gz"
            path.write_bytes(b"not a gzip cache")
            with self.assertRaises(OSError):
                read_cache(path)


if __name__ == "__main__":
    unittest.main()
