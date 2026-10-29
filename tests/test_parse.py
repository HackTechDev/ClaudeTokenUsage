"""Tests de l'analyse des réponses de l'endpoint d'usage."""
import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_usage import UsageError, format_remaining, parse_usage

# Réponse fictive au format actuel de l'API
RESPONSE = {
    "five_hour": {"utilization": 16.0, "resets_at": "2026-10-29T22:49:59.631025+00:00"},
    "seven_day": {"utilization": 84.0, "resets_at": "2026-10-30T11:59:59.631051+00:00"},
    "seven_day_opus": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": 1700, "used_credits": 1006.0,
                    "currency": "EUR", "decimal_places": 2, "disabled_reason": "out_of_credits"},
    "seven_day_breakdown": {"rows": [
        {"key": "claude_code", "display_name": "Claude Code", "percent": 98},
        {"key": "chat", "display_name": "Chats", "percent": 2},
        {"key": "other", "display_name": "Other", "percent": 0},
    ]},
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
        usage = parse_usage({})
        self.assertEqual((usage.limits, usage.extra, usage.breakdown), ([], None, []))

    def test_extra_usage(self):
        extra = parse_usage(RESPONSE).extra
        self.assertEqual((extra.used, extra.limit, extra.currency), (10.06, 17.0, "EUR"))
        self.assertEqual(extra.describe(), "10,06 / 17,00 EUR (59 %) · désactivés : crédits épuisés")

    def test_breakdown_hides_zero(self):
        usage = parse_usage(RESPONSE)
        self.assertEqual(len(usage.breakdown), 3)
        self.assertEqual(usage.describe_breakdown(), "Claude Code 98 % · Chats 2 %")

    def test_malformed_secondary_sections_are_ignored(self):
        data = dict(RESPONSE, extra_usage={"is_enabled": True}, seven_day_breakdown="oups")
        usage = parse_usage(data)
        self.assertEqual((usage.extra, usage.breakdown), (None, []))
        self.assertEqual(len(usage.limits), 2)

    def test_malformed_response(self):
        for data in ({"limits": [{"kind": "session"}]},
                     {"limits": [{"kind": "s", "percent": 1, "resets_at": "pas une date"}]},
                     {"five_hour": {"utilization": 1}},
                     {"limits": "oups"}):
            with self.subTest(data=data), self.assertRaises(UsageError):
                parse_usage(data)


class FormatRemainingTest(unittest.TestCase):
    def test_formats(self):
        cases = [(timedelta(days=2, hours=3, minutes=10), "2 j 3 h"),
                 (timedelta(hours=4, minutes=5), "4 h 05"),
                 (timedelta(minutes=12, seconds=40), "12 min"),
                 (timedelta(seconds=30), "< 1 min"),
                 (timedelta(0), "< 1 min")]
        for delta, expected in cases:
            with self.subTest(delta=delta):
                self.assertEqual(format_remaining(delta), expected)

    def test_remaining_never_negative(self):
        limit = parse_usage(RESPONSE).limits[0]
        later = limit.resets_at + timedelta(hours=1)
        self.assertEqual(limit.remaining(later), timedelta(0))


class PaceTest(unittest.TestCase):
    def setUp(self):
        self.limit = parse_usage(RESPONSE).limits[0]  # session de 5 h, 16 %
        self.reset = self.limit.resets_at

    def test_pace_and_exhaustion(self):
        # 1 h écoulée sur 5 h (20 %) pour 16 % consommés : rythme 0.8, pas d'épuisement
        now = self.reset - timedelta(hours=4)
        self.assertAlmostEqual(self.limit.pace(now), 0.8)
        self.assertIsNone(self.limit.exhaustion(now))

    def test_exhaustion_before_reset(self):
        # 16 % en 30 min : 100 % atteints 30 min × 84/16 = 2 h 37 min 30 s plus tard
        now = self.reset - timedelta(hours=4, minutes=30)
        self.assertAlmostEqual(self.limit.pace(now), 1.6)
        self.assertEqual(self.limit.exhaustion(now), now + timedelta(hours=2, minutes=37, seconds=30))

    def test_too_early_for_pace(self):
        now = self.reset - timedelta(hours=4, minutes=50)
        self.assertIsNone(self.limit.pace(now))
        self.assertIsNone(self.limit.exhaustion(now))


if __name__ == "__main__":
    unittest.main()
