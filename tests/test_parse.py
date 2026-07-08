import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parse  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestParsers(unittest.TestCase):
    def test_sysbench_cpu(self):
        text = (FIXTURES / "sysbench_cpu.txt").read_text()
        metrics = parse.parse_sysbench_cpu(text)
        metric = metrics["sysbench_cpu_events_per_sec"]
        self.assertEqual(metric["value"], 58783452.97)
        self.assertEqual(metric["unit"], "events/s")
        self.assertTrue(metric["higher_is_better"])

    def test_sysbench_memory(self):
        text = (FIXTURES / "sysbench_memory.txt").read_text()
        metrics = parse.parse_sysbench_memory(text)
        metric = metrics["sysbench_memory_mib_per_sec"]
        self.assertEqual(metric["value"], 8745.98)
        self.assertEqual(metric["unit"], "MiB/s")
        self.assertTrue(metric["higher_is_better"])

    def test_stress_ng_cpu(self):
        text = (FIXTURES / "stress_ng_cpu.txt").read_text()
        metrics = parse.parse_stress_ng_cpu(text)
        metric = metrics["stressng_cpu_bogo_ops_per_sec"]
        self.assertEqual(metric["value"], 14572.79)
        self.assertEqual(metric["unit"], "bogo-ops/s")
        self.assertTrue(metric["higher_is_better"])

    def test_fio_randread(self):
        text = (FIXTURES / "fio_randread.txt").read_text()
        metrics = parse.parse_fio_randread(text)
        self.assertEqual(metrics["fio_randread_iops"]["value"], 19032.8)
        self.assertEqual(metrics["fio_randread_iops"]["unit"], "IOPS")
        self.assertEqual(metrics["fio_randread_bw_kibps"]["value"], 76131)
        self.assertEqual(metrics["fio_randread_bw_kibps"]["unit"], "KiB/s")

    def test_sysbench_cpu_missing_line_raises(self):
        with self.assertRaises(ValueError):
            parse.parse_sysbench_cpu("garbage output with no matching line")

    def test_stress_ng_cpu_missing_line_raises(self):
        with self.assertRaises(ValueError):
            parse.parse_stress_ng_cpu("garbage output with no matching line")


if __name__ == "__main__":
    unittest.main()
