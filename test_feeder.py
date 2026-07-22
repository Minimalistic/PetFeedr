"""Tests for schedule parsing, randomization, and log-parsing stats.

Run: python3 -m unittest
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import feeding_stats
from feeder_core import parse_schedule_line, apply_random_offset


class TestParseScheduleLine(unittest.TestCase):
    def test_full_line(self):
        self.assertEqual(parse_schedule_line("08:00,medium,fixed"), ("08:00", "medium", True))

    def test_time_only_defaults(self):
        self.assertEqual(parse_schedule_line("08:00"), ("08:00", "small", False))

    def test_unknown_portion_falls_back(self):
        self.assertEqual(parse_schedule_line("08:00,bogus"), ("08:00", "small", False))

    def test_randomized_with_portion(self):
        self.assertEqual(parse_schedule_line("21:30,large"), ("21:30", "large", False))

    def test_whitespace_tolerated(self):
        self.assertEqual(parse_schedule_line(" 08:00 , medium , FIXED \n"), ("08:00", "medium", True))

    def test_legacy_fixed_in_portion_slot_not_recognized(self):
        # Quirk pinned: "HH:MM,fixed" is NOT treated as fixed by the scheduler
        # (the web UI displays it as fixed — known inconsistency).
        self.assertEqual(parse_schedule_line("08:00,fixed"), ("08:00", "small", False))


class TestApplyRandomOffset(unittest.TestCase):
    def test_offset_applied(self):
        with patch('feeder_core.random.randint', return_value=15):
            self.assertEqual(apply_random_offset("08:00", 30, []), "08:15")

    def test_negative_offset(self):
        with patch('feeder_core.random.randint', return_value=-30):
            self.assertEqual(apply_random_offset("08:00", 30, []), "07:30")

    def test_backward_past_midnight_clamps_to_base(self):
        with patch('feeder_core.random.randint', return_value=-30):
            self.assertEqual(apply_random_offset("00:10", 30, []), "00:10")

    def test_forward_past_midnight_wraps(self):
        # Quirk pinned: a forward offset can cross midnight and produce an
        # early-morning time ("00:20") rather than clamping.
        with patch('feeder_core.random.randint', return_value=30):
            self.assertEqual(apply_random_offset("23:50", 30, []), "00:20")

    def test_conflict_avoidance_retries(self):
        # First offset lands within 10 min of an existing time, second is clear.
        existing = [datetime.strptime("08:15", "%H:%M")]
        with patch('feeder_core.random.randint', side_effect=[10, -20]):
            self.assertEqual(apply_random_offset("08:00", 30, existing), "07:40")

    def test_exact_collision_allowed(self):
        # Quirk pinned: "diff > 0" in the conflict check means landing on
        # exactly the same minute as another feeding is NOT a conflict.
        existing = [datetime.strptime("08:15", "%H:%M")]
        with patch('feeder_core.random.randint', return_value=15):
            self.assertEqual(apply_random_offset("08:00", 30, existing), "08:15")

    def test_gives_up_after_ten_tries(self):
        existing = [datetime.strptime("08:03", "%H:%M")]
        with patch('feeder_core.random.randint', return_value=5):
            self.assertEqual(apply_random_offset("08:00", 30, existing), "08:00")


# Real log line shapes observed in production and dev
PLAIN_MANUAL = "2026-04-15 07:15:07 - Manual feeding triggered (small portion)"
PLAIN_SCHEDULED = "2026-04-15 07:15:07 - Feeding at 07:15 AM (small portion)"
INFO_COMPLETED = "2026-05-10 04:00:00,391 - INFO - Feeding completed in 0.31s (small portion)"
INFO_MANUAL = "2026-07-11 21:32:23,525 - INFO - Manual feeding triggered (small portion)"
SIM_COMPLETED = "2026-03-22 00:21:34,508 - INFO - [SIM] ✅ Feeding completed in 0.92s (medium portion)"
WERKZEUG = '2026-04-29 12:34:44,239 - INFO - 192.168.1.10 - - [29/Apr/2026 12:34:44] "GET /sw.js HTTP/1.1" 200 -'


class TestLogPatterns(unittest.TestCase):
    """Pin current regex behavior, including known gaps fixed in a later commit."""

    def test_plain_manual_matches(self):
        m = feeding_stats.MANUAL_PAT.match(PLAIN_MANUAL)
        self.assertEqual(m.groups(), ("2026-04-15", "07:15:07", "small"))

    def test_plain_scheduled_matches(self):
        m = feeding_stats.SCHED_PAT.match(PLAIN_SCHEDULED)
        self.assertEqual(m.groups(), ("2026-04-15", "07:15:07", "small"))

    def test_info_completed_matches(self):
        m = feeding_stats.COMPLETED_PAT.match(INFO_COMPLETED)
        self.assertEqual(m.groups(), ("2026-05-10", "04:00:00", "small"))

    def test_info_manual_not_matched_yet(self):
        # Known bug pinned: live-Pi manual lines carry ",ms - INFO -" and are missed.
        self.assertIsNone(feeding_stats.MANUAL_PAT.match(INFO_MANUAL))

    def test_sim_completed_not_matched_yet(self):
        # Known gap pinned: "[SIM] ✅ " prefix defeats the completed pattern.
        self.assertIsNone(feeding_stats.COMPLETED_PAT.match(SIM_COMPLETED))

    def test_werkzeug_noise_never_matches(self):
        for pat in (feeding_stats.MANUAL_PAT, feeding_stats.SCHED_PAT, feeding_stats.COMPLETED_PAT):
            self.assertIsNone(pat.match(WERKZEUG))


def _line(days_ago, time_str, kind, portion):
    d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    if kind == 'manual':
        return f"{d} {time_str} - Manual feeding triggered ({portion} portion)\n"
    return f"{d} {time_str},391 - INFO - Feeding completed in 0.31s ({portion} portion)\n"


class TestWeeklyStats(unittest.TestCase):
    def test_aggregates_by_day_and_portion(self):
        lines = [
            _line(0, "06:00:00", 'completed', 'small'),
            _line(0, "18:00:00", 'completed', 'medium'),
            _line(1, "07:00:00", 'manual', 'large'),
        ]
        stats = feeding_stats.parse_weekly_stats(lines=lines)
        self.assertEqual(len(stats), 7)
        today = stats[-1]
        self.assertTrue(today['is_today'])
        self.assertEqual((today['small'], today['medium'], today['total_feedings']), (1, 1, 2))
        self.assertAlmostEqual(today['total_cups'], 0.75)
        yesterday = stats[-2]
        self.assertEqual((yesterday['large'], yesterday['manual_count']), (1, 1))

    def test_old_lines_ignored(self):
        stats = feeding_stats.parse_weekly_stats(lines=[_line(10, "06:00:00", 'completed', 'small')])
        self.assertEqual(sum(d['total_feedings'] for d in stats), 0)


class TestRecentActivity(unittest.TestCase):
    def test_newest_first_with_types(self):
        lines = [
            _line(1, "07:00:00", 'manual', 'large'),
            _line(0, "06:00:00", 'completed', 'small'),
        ]
        activity = feeding_stats.parse_recent_activity(days=14, limit=50, lines=lines)
        self.assertEqual(len(activity), 2)
        self.assertEqual((activity[0]['date'], activity[0]['type']), ("Today", 'scheduled'))
        self.assertEqual((activity[1]['date'], activity[1]['type']), ("Yesterday", 'manual'))

    def test_limit_respected(self):
        lines = [_line(0, f"0{h}:00:00", 'completed', 'small') for h in range(1, 6)]
        self.assertEqual(len(feeding_stats.parse_recent_activity(limit=2, lines=lines)), 2)


class TestDayFeedings(unittest.TestCase):
    def test_filters_to_requested_date(self):
        target = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        lines = [
            _line(1, "07:00:00", 'manual', 'large'),
            _line(0, "06:00:00", 'completed', 'small'),
        ]
        feedings, total = feeding_stats.day_feedings(target, lines=lines)
        self.assertEqual(len(feedings), 1)
        self.assertEqual((feedings[0]['time'], feedings[0]['type']), ("7:00 AM", 'manual'))
        self.assertAlmostEqual(total, 0.75)


class TestTotals(unittest.TestCase):
    def test_daily_total_mixed_portions(self):
        scheds = [{'portion': 'small'}, {'portion': 'medium'}, {'portion': 'large'}, {'portion': 'bogus'}]
        self.assertAlmostEqual(feeding_stats.calculate_daily_total(scheds), 1.75)

    def test_week_summary_variants(self):
        empty = feeding_stats.parse_weekly_stats(lines=["\n"])
        self.assertIsNone(feeding_stats.build_week_summary(empty))
        stats = feeding_stats.parse_weekly_stats(lines=[_line(0, "06:00:00", 'completed', 'small')])
        self.assertEqual(feeding_stats.build_week_summary(stats), "All feedings on schedule")
        stats = feeding_stats.parse_weekly_stats(lines=[_line(0, "06:00:00", 'manual', 'small')])
        self.assertEqual(feeding_stats.build_week_summary(stats), "1 manual feed this week")

    def test_consumption_rate(self):
        stats = feeding_stats.parse_weekly_stats(lines=[
            _line(0, "06:00:00", 'completed', 'medium'),
            _line(1, "06:00:00", 'completed', 'medium'),
        ])
        rate = feeding_stats.calculate_consumption_rate(stats)
        self.assertEqual(rate['daily_cups'], 0.5)
        self.assertEqual(rate['weekly_cups'], 3.5)
        self.assertIsNone(feeding_stats.calculate_consumption_rate(
            feeding_stats.parse_weekly_stats(lines=["\n"])))


if __name__ == '__main__':
    unittest.main()
