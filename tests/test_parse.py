"""Tests de l'analyse des réponses de l'endpoint d'usage."""
import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_usage import UsageError, parse_usage

# Réponse fictive au format actuel de l'API
RESPONSE = {
    "five_hour": {"utilization": 16.0, "resets_at": "2026-10-29T22:49:59.631025+00:00"},
    "seven_day": {"utilization": 84.0, "resets_at": "2026-10-30T11:59:59.631051+00:00"},
    "seven_day_opus": None,
    "limits": [
        {"kind": "session", "group": "session", "percent": 16,
         "resets_at": "2026-10-29T22:49:59.631025+00:00"},
        {"kind": "weekly_all", "group": "weekly", "percent": 84,
         "resets_at": "2026-10-30T11:59:59.631051+00:00"},
    ],
}


class ParseUsageTest(unittest.TestCase):
    def test_limits_array(self):
        usage = parse_usage(RESPONSE)
        self.assertEqual([l.kind for l in usage.limits], ["session", "weekly_all"])
        self.assertEqual([l.label for l in usage.limits], ["Session (5 h)", "Hebdomadaire"])
        self.assertEqual([l.percent for l in usage.limits], [16.0, 84.0])
        self.assertEqual(usage.limits[0].window, timedelta(hours=5))
        self.assertEqual(usage.limits[1].window, timedelta(days=7))

    def test_reset_rounded_to_minute(self):
        # 22:49:59.63 UTC -> 22:50 UTC, exprimée dans le fuseau local
        reset = parse_usage(RESPONSE).limits[0].resets_at
        self.assertEqual(reset, datetime(2026, 10, 29, 22, 50, tzinfo=timezone.utc))
        self.assertIsNotNone(reset.utcoffset())

    def test_unknown_kind_gets_readable_label(self):
        data = {"limits": [{"kind": "weekly_haiku", "group": "weekly", "percent": 5,
                            "resets_at": "2026-10-30T12:00:00+00:00"}]}
        limit = parse_usage(data).limits[0]
        self.assertEqual(limit.label, "Weekly haiku")
        self.assertEqual(limit.window, timedelta(days=7))

    def test_unknown_group_has_no_window(self):
        data = {"limits": [{"kind": "x", "group": "monthly", "percent": 5,
                            "resets_at": "2026-10-30T12:00:00+00:00"}]}
        self.assertIsNone(parse_usage(data).limits[0].window)

    def test_legacy_keys_when_no_limits_array(self):
        data = {k: v for k, v in RESPONSE.items() if k != "limits"}
        usage = parse_usage(data)
        self.assertEqual([l.kind for l in usage.limits], ["session", "weekly_all"])
        self.assertEqual([l.percent for l in usage.limits], [16.0, 84.0])

    def test_empty_response(self):
        self.assertEqual(parse_usage({}).limits, [])

    def test_malformed_response(self):
        for data in ({"limits": [{"kind": "session"}]},
                     {"limits": [{"kind": "s", "percent": 1, "resets_at": "pas une date"}]},
                     {"five_hour": {"utilization": 1}},
                     {"limits": "oups"}):
            with self.subTest(data=data), self.assertRaises(UsageError):
                parse_usage(data)


if __name__ == "__main__":
    unittest.main()
