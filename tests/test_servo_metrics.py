"""Settling criteria must handle dwell, late excursions, gaps, and truncation."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from servo_metrics import percentile, rolling_mean, summarize


def rows(offsets, times=None):
    if times is None:
        times = [i * .25 for i in range(len(offsets))]
    return [dict(t_ns=[int(t * 1e9), 0, 0, 0], offset_ns=o, rate_ppb=0)
            for t, o in zip(times, offsets)]


class ServoMetricsTests(unittest.TestCase):
    def test_entry_and_confirmation_are_separate(self):
        result = summarize(rows([200] * 40 + [10] * 161), stability_seconds=30)
        self.assertEqual(result['settling_entry_seconds'], 10)
        self.assertEqual(result['settling_confirmed_seconds'], 30)
        self.assertEqual(result['last_exit_settling_seconds'], 10)
        self.assertEqual(result['stability_mean_offset_ns'], 10)
        self.assertEqual(result['stability_rms_offset_ns'], 10)
        self.assertEqual(result['stability_stddev_offset_ns'], 0)

    def test_a_brief_crossing_does_not_settle(self):
        values = [0] * 40 + [200] * 40 + [0] * 81
        result = summarize(rows(values), stability_seconds=30)
        self.assertEqual(result['settling_entry_seconds'], 20)
        self.assertEqual(result['settling_confirmed_seconds'], 40)

    def test_late_excursion_requires_reentry(self):
        values = [0] * 120 + [101] + [0] * 80
        result = summarize(rows(values), stability_seconds=30)
        self.assertEqual(result['settling_entry_seconds'], 0)
        self.assertEqual(result['excursions_after_confirmation'], 1)
        self.assertIsNone(result['last_exit_settling_seconds'])
        result = summarize(rows(values + [0]), stability_seconds=30)
        self.assertEqual(result['last_exit_settling_seconds'], 30.25)

    def test_missing_samples_break_dwell(self):
        times = [i * .25 for i in range(60)] + [30 + i * .25 for i in range(81)]
        result = summarize(rows([0] * len(times), times), stability_seconds=30)
        self.assertEqual(result['sample_gaps_over_limit'], 1)
        self.assertEqual(result['settling_entry_seconds'], 30)

    def test_unsettled_and_short_captures(self):
        result = summarize(rows([101] * 161), stability_seconds=30)
        self.assertIsNone(result['settling_entry_seconds'])
        self.assertIsNone(result['last_exit_settling_seconds'])
        with self.assertRaises(ValueError):
            summarize(rows([0] * 40), stability_seconds=30)
        with self.assertRaises(ValueError):
            summarize(rows([0] * 121, [0] * 121), stability_seconds=30)

    def test_inclusive_band_and_quantiles(self):
        result = summarize(rows([100] * 161), stability_seconds=30)
        self.assertEqual(result['settling_entry_seconds'], 0)
        self.assertEqual(result['stability_in_band_fraction'], 1)
        self.assertEqual(percentile([0, 10, 20, 30], .5), 15)
        self.assertEqual(rolling_mean([0, 1, 2, 3], [1, 2, 3, 4], 2)[2:], [2, 3])


if __name__ == '__main__':
    unittest.main()
