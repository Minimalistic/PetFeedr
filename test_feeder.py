"""Tests for schedule parsing, randomization, and log-parsing stats.

Run: python3 -m unittest
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, date
from unittest.mock import patch

import schedule

import feeder_core
import feeding_stats
from feeder_core import apply_random_offset
from schedule_store import parse_line as parse_schedule_line


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

    def test_legacy_fixed_in_portion_slot_is_fixed(self):
        # One parser now: the scheduler honors "HH:MM,fixed" the way the UI
        # always displayed it (they used to disagree).
        self.assertEqual(parse_schedule_line("08:00,fixed"), ("08:00", "small", True))


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


# Real log line shapes: every historical format plus the current schema
NEW_MANUAL = "2026-07-22 14:00:00,430 - INFO - Feeding completed in 0.31s (small portion, manual)"
NEW_SCHEDULED = "2026-07-22 06:00:00,101 - INFO - Feeding completed in 0.62s (medium portion, scheduled)"
LEGACY_COMPLETED = "2026-05-10 04:00:00,391 - INFO - Feeding completed in 0.31s (small portion)"
SIM_COMPLETED = "2026-03-22 00:21:34,508 - INFO - [SIM] ✅ Feeding completed in 0.92s (medium portion)"
SIM_NEW = "2026-07-22 15:09:01,195 - INFO - [SIM] ✅ Feeding completed in 0.94s (medium portion, manual)"
PLAIN_COMPLETED = "2026-04-15 07:15:07 - Feeding completed in 0.31s (small portion)"
FAILED = "2026-07-22 08:00:01,001 - ERROR - Feeding failed (large portion, scheduled): jam"
LEGACY_MANUAL_TRIGGERED = "2026-07-11 21:32:23,525 - INFO - Manual feeding triggered (small portion)"
LEGACY_FEEDING_AT = "2026-04-15 07:15:07 - Feeding at 07:15 AM (small portion)"
WERKZEUG = '2026-04-29 12:34:44,239 - INFO - 192.168.1.10 - - [29/Apr/2026 12:34:44] "GET /sw.js HTTP/1.1" 200 -'


class TestLogPatterns(unittest.TestCase):
    def test_completed_matrix(self):
        cases = [
            (NEW_MANUAL, ("2026-07-22", "14:00:00", "small", "manual")),
            (NEW_SCHEDULED, ("2026-07-22", "06:00:00", "medium", "scheduled")),
            (LEGACY_COMPLETED, ("2026-05-10", "04:00:00", "small", None)),
            (SIM_COMPLETED, ("2026-03-22", "00:21:34", "medium", None)),
            (SIM_NEW, ("2026-07-22", "15:09:01", "medium", "manual")),
            (PLAIN_COMPLETED, ("2026-04-15", "07:15:07", "small", None)),
        ]
        for line, expected in cases:
            m = feeding_stats.COMPLETED_RE.match(line)
            self.assertIsNotNone(m, line)
            self.assertEqual((m['date'], m['time'], m['portion'], m['source']), expected, line)

    def test_failed_line_matches_failed_only(self):
        m = feeding_stats.FAILED_RE.match(FAILED)
        self.assertEqual((m['portion'], m['source']), ("large", "scheduled"))
        self.assertIsNone(feeding_stats.COMPLETED_RE.match(FAILED))

    def test_non_dispense_lines_never_match(self):
        # Legacy trigger/announce lines had companion completed lines —
        # counting them would double-count. Werkzeug noise must never match.
        for line in (LEGACY_MANUAL_TRIGGERED, LEGACY_FEEDING_AT, WERKZEUG):
            self.assertIsNone(feeding_stats.COMPLETED_RE.match(line), line)


def _line(days_ago, time_str, kind, portion):
    d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    if kind == 'legacy':
        return f"{d} {time_str},391 - INFO - Feeding completed in 0.31s ({portion} portion)\n"
    return f"{d} {time_str},391 - INFO - Feeding completed in 0.31s ({portion} portion, {kind})\n"


class TestWeeklyStats(unittest.TestCase):
    def test_aggregates_by_day_and_portion(self):
        lines = [
            _line(0, "06:00:00", 'scheduled', 'small'),
            _line(0, "18:00:00", 'scheduled', 'medium'),
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

    def test_legacy_lines_count_as_scheduled(self):
        stats = feeding_stats.parse_weekly_stats(lines=[_line(0, "06:00:00", 'legacy', 'small')])
        today = stats[-1]
        self.assertEqual((today['total_feedings'], today['manual_count']), (1, 0))

    def test_old_lines_ignored(self):
        stats = feeding_stats.parse_weekly_stats(lines=[_line(10, "06:00:00", 'scheduled', 'small')])
        self.assertEqual(sum(d['total_feedings'] for d in stats), 0)


class TestRecentActivity(unittest.TestCase):
    def test_newest_first_with_types(self):
        lines = [
            _line(1, "07:00:00", 'manual', 'large'),
            _line(0, "06:00:00", 'scheduled', 'small'),
        ]
        activity = feeding_stats.parse_recent_activity(days=14, limit=50, lines=lines)
        self.assertEqual(len(activity), 2)
        self.assertEqual((activity[0]['date'], activity[0]['type']), ("Today", 'scheduled'))
        self.assertEqual((activity[1]['date'], activity[1]['type']), ("Yesterday", 'manual'))

    def test_limit_respected(self):
        lines = [_line(0, f"0{h}:00:00", 'scheduled', 'small') for h in range(1, 6)]
        self.assertEqual(len(feeding_stats.parse_recent_activity(limit=2, lines=lines)), 2)


class TestDayFeedings(unittest.TestCase):
    def test_filters_to_requested_date(self):
        target = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        lines = [
            _line(1, "07:00:00", 'manual', 'large'),
            _line(0, "06:00:00", 'scheduled', 'small'),
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
        stats = feeding_stats.parse_weekly_stats(lines=[_line(0, "06:00:00", 'scheduled', 'small')])
        self.assertEqual(feeding_stats.build_week_summary(stats), "All feedings on schedule")
        stats = feeding_stats.parse_weekly_stats(lines=[_line(0, "06:00:00", 'manual', 'small')])
        self.assertEqual(feeding_stats.build_week_summary(stats), "1 manual feed this week")

    def test_consumption_rate(self):
        stats = feeding_stats.parse_weekly_stats(lines=[
            _line(0, "06:00:00", 'scheduled', 'medium'),
            _line(1, "06:00:00", 'scheduled', 'medium'),
        ])
        rate = feeding_stats.calculate_consumption_rate(stats)
        self.assertEqual(rate['daily_cups'], 0.5)
        self.assertEqual(rate['weekly_cups'], 3.5)
        self.assertIsNone(feeding_stats.calculate_consumption_rate(
            feeding_stats.parse_weekly_stats(lines=["\n"])))


class TempCwd(unittest.TestCase):
    """Run in a scratch directory so tests never touch the repo's runtime files."""

    def setUp(self):
        self._olddir = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._olddir)
        self._tmp.cleanup()


class TestFailureHandling(TempCwd):
    def test_notify_unconfigured_is_noop(self):
        import notify
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('PUSHOVER_TOKEN', None)
            os.environ.pop('PUSHOVER_USER', None)
            self.assertFalse(notify.send("test"))  # no exception, no network

    def test_sim_mode_suppresses_even_with_creds(self):
        # A dev box with real Pushover creds in the shell env must never
        # page a phone from a simulation run.
        import notify
        with patch.dict(os.environ, {'PUSHOVER_TOKEN': 'x', 'PUSHOVER_USER': 'y'}), \
             patch('notify.SIMULATION_MODE', True), \
             patch('notify.urllib.request.urlopen') as mock_open:
            os.environ.pop('PETFEEDR_NOTIFY_IN_SIM', None)
            self.assertFalse(notify.send("test"))
            mock_open.assert_not_called()

    def test_sim_override_allows_send(self):
        import notify
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.__enter__.return_value.status = 200
        with patch.dict(os.environ, {'PUSHOVER_TOKEN': 'x', 'PUSHOVER_USER': 'y',
                                     'PETFEEDR_NOTIFY_IN_SIM': 'true'}), \
             patch('notify.SIMULATION_MODE', True), \
             patch('notify.urllib.request.urlopen', return_value=resp) as mock_open:
            self.assertTrue(notify.send("test"))
            mock_open.assert_called_once()

    def test_feed_pet_failure_returns_false_and_notifies(self):
        with patch('feeder_core.trigger_servo', side_effect=RuntimeError("jam")), \
             patch('feeder_core.notify.send') as mock_send:
            self.assertFalse(feeder_core.feed_pet(portion='large', source='manual'))
            self.assertIn("large portion, manual", mock_send.call_args[0][0])

    def test_feed_pet_success_returns_true_without_notifying(self):
        with patch('feeder_core.trigger_servo', return_value=0.2), \
             patch('feeder_core.notify.send') as mock_send:
            self.assertTrue(feeder_core.feed_pet())
            mock_send.assert_not_called()


class TestResync(unittest.TestCase):
    """Job-registry sync against todays_schedule.json (runs in a temp cwd)."""

    def setUp(self):
        self._olddir = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        schedule.clear()

    def tearDown(self):
        schedule.clear()
        os.chdir(self._olddir)
        self._tmp.cleanup()

    @staticmethod
    def _entry(actual_time, portion='small'):
        return {'base_time': actual_time, 'actual_time': actual_time,
                'portion': portion, 'is_fixed': True, 'randomized': False}

    def test_passed_time_registers_for_tomorrow(self):
        # 00:00 has always passed by the time this runs → next_run is
        # tomorrow, so resyncing after a feeding fired never re-fires it.
        feeder_core.save_todays_schedule([self._entry('00:00')])
        feeder_core.resync_today()
        self.assertEqual(len(schedule.jobs), 1)
        self.assertEqual(schedule.jobs[0].next_run.date(), date.today() + timedelta(days=1))

    def test_resync_fires_due_job_before_clearing(self):
        # A job that came due just before a mutation must fire, not vanish.
        fired = []
        job = schedule.every().day.at("00:00").do(lambda: fired.append(1))
        job.next_run = datetime.now() - timedelta(seconds=1)
        feeder_core.resync_today()
        self.assertEqual(fired, [1])

    def test_resync_replaces_registry_from_file(self):
        schedule.every().day.at("00:00").do(lambda: None)  # stale job
        feeder_core.save_todays_schedule([self._entry('00:00'), self._entry('00:01', 'large')])
        feeder_core.resync_today()
        self.assertEqual(len(schedule.jobs), 2)

    def test_resync_with_no_file_leaves_registry_empty(self):
        schedule.every().day.at("00:00").do(lambda: None)
        feeder_core.resync_today()
        self.assertEqual(schedule.jobs, [])

    def test_ensure_today_preserves_current_schedule(self):
        # Restart fix: today's already-rolled times must NOT be re-randomized.
        entries = [self._entry('00:00', 'medium')]
        feeder_core.save_todays_schedule(entries)
        self.assertEqual(feeder_core.ensure_today(), entries)
        self.assertEqual(len(schedule.jobs), 1)

    def test_ensure_today_regenerates_stale_file(self):
        with open('feeding_schedules.txt', 'w') as f:
            f.write("08:00,medium,fixed\n")
        stale = {'date': (date.today() - timedelta(days=1)).isoformat(),
                 'schedule': [self._entry('09:30')]}
        import json
        with open(feeder_core.TODAYS_SCHEDULE_FILE, 'w') as f:
            json.dump(stale, f)
        result = feeder_core.ensure_today()
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['actual_time'], result[0]['portion']), ('08:00', 'medium'))
        self.assertEqual(len(schedule.jobs), 1)

    def test_generate_with_empty_schedules_saves_empty_today(self):
        open('feeding_schedules.txt', 'w').close()
        self.assertEqual(feeder_core.generate_todays_schedule(), [])
        self.assertEqual(feeder_core.load_todays_schedule(), [])


class TestHopper(TempCwd):
    """Hopper learning and low-warning logic."""

    def test_fresh_state_is_learning(self):
        import hopper
        info = hopper.status()
        self.assertTrue(info['learning'])
        self.assertEqual(info['cups_since_refill'], 0.0)
        self.assertIsNone(info['days_left'])

    def test_refill_learns_capacity_and_resets_counter(self):
        import hopper
        for _ in range(4):
            hopper.record_dispense(2.5)  # 10 cups total
        state = hopper.record_refill(25)  # 25% left → consumed 75% → ~13.33 cups
        self.assertAlmostEqual(hopper.capacity_cups(state), 13.33, places=2)
        self.assertEqual(state['cups_since_refill'], 0.0)
        info = hopper.status(daily_avg_cups=1.0)
        self.assertFalse(info['learning'])
        self.assertEqual(info['level'], 1.0)
        self.assertEqual(info['days_left'], 13)

    def test_weighed_refill_learns_cups_per_lb(self):
        import hopper
        for _ in range(4):
            hopper.record_dispense(2.5)  # 10 cups total
        state = hopper.record_refill(25, lbs_added=2.5)  # 10 cups / 2.5 lb
        self.assertEqual(hopper.cups_per_lb(state), 4.0)
        self.assertEqual(hopper.status()['cups_per_lb'], 4.0)
        # 2.5 lb refilled 75% of the hopper → holds ~3.3 lb
        self.assertEqual(hopper.status()['capacity_lbs'], 3.3)

    def test_unweighed_refill_leaves_cups_per_lb_unknown(self):
        import hopper
        hopper.record_dispense(10)
        state = hopper.record_refill(25)
        self.assertIsNone(hopper.cups_per_lb(state))
        self.assertIsNone(hopper.capacity_lbs(state))

    def test_index_shows_capacity_in_lb_and_oz_once_weighed(self):
        import hopper
        import web_interface
        hopper.record_dispense(22.96)
        hopper.record_refill(12.5, lbs_added=7)
        html = web_interface.app.test_client().get('/').get_data(as_text=True)
        self.assertIn('holds ~8 lb (128 oz), ~26.24 cups', html)
        self.assertIn('~100% full (~8 lb left)', html)
        hopper.record_dispense(13.12)  # half of 26.24 cups
        html = web_interface.app.test_client().get('/').get_data(as_text=True)
        self.assertIn('~50% full (~4 lb left)', html)

    def test_index_shows_cups_only_when_never_weighed(self):
        import hopper
        import web_interface
        hopper.record_dispense(10)
        hopper.record_refill(25)
        html = web_interface.app.test_client().get('/').get_data(as_text=True)
        self.assertIn('holds ~13.33 cups', html)
        self.assertNotIn(' oz)', html)
        self.assertNotIn('lb left', html)

    def test_weighed_refill_after_trivial_consumption_learns_nothing(self):
        import hopper
        hopper.record_dispense(0.5)
        state = hopper.record_refill(10, lbs_added=7)
        self.assertEqual(state['cups_per_lb_estimates'], [])

    def test_refill_without_dispenses_learns_nothing(self):
        import hopper
        state = hopper.record_refill(50)
        self.assertIsNone(hopper.capacity_cups(state))

    def test_refill_after_trivial_consumption_resets_but_learns_nothing(self):
        import hopper
        hopper.record_dispense(0.5)  # below MIN_LEARN_CUPS
        state = hopper.record_refill(10)
        self.assertIsNone(hopper.capacity_cups(state))
        self.assertEqual(state['cups_since_refill'], 0.0)

    def test_refill_at_learning_floor_still_learns(self):
        import hopper
        hopper.record_dispense(hopper.MIN_LEARN_CUPS)
        state = hopper.record_refill(0)  # emptied → capacity = cups dispensed
        self.assertAlmostEqual(hopper.capacity_cups(state), hopper.MIN_LEARN_CUPS)

    def test_capacity_is_median_of_recent_estimates(self):
        import hopper
        for est_source in [(7.5, 25), (10.0, 0), (20.0, 0)]:  # → 10, 10, 20
            cups, pct = est_source
            hopper.record_dispense(cups)
            hopper.record_refill(pct)
        self.assertAlmostEqual(hopper.capacity_cups(hopper.load_state()), 10.0)

    def test_low_warning_fires_once_per_cycle(self):
        import hopper
        hopper.record_dispense(9.0)
        hopper.record_refill(10)  # capacity ~10 cups
        hopper.record_dispense(9.0)  # 10% left → low
        self.assertIsNotNone(hopper.check_low(daily_avg_cups=1.0))
        self.assertIsNone(hopper.check_low(daily_avg_cups=1.0))  # already notified
        hopper.record_refill(10)  # reset re-arms the warning
        hopper.record_dispense(9.5)
        self.assertIsNotNone(hopper.check_low(daily_avg_cups=1.0))

    def test_corrupt_state_file_resets(self):
        import hopper
        with open(hopper.HOPPER_FILE, 'w') as f:
            f.write("not json{")
        info = hopper.status()
        self.assertTrue(info['learning'])

    def test_index_preselects_refill_guess_near_estimated_level(self):
        import hopper
        import web_interface
        hopper.record_dispense(9.0)
        hopper.record_refill(10)     # capacity ~10 cups
        hopper.record_dispense(4.0)  # level 0.6 → nearest choice is 50
        html = web_interface.app.test_client().get('/').data.decode()
        self.assertIn('<option value="50" selected>', html)

    def test_index_refill_guess_defaults_to_10_while_learning(self):
        import web_interface
        html = web_interface.app.test_client().get('/').data.decode()
        self.assertIn('<option value="10" selected>', html)

    def test_refill_route_validates_percentage(self):
        import web_interface
        client = web_interface.app.test_client()
        for bad in ('abc', '', '120', '-5'):
            r = client.post('/refill', data={'remaining_pct': bad},
                            headers={'Accept': 'application/json'})
            self.assertEqual(r.status_code, 400, bad)
            self.assertFalse(r.get_json()['success'])
        r = client.post('/refill', data={'remaining_pct': '25'},
                        headers={'Accept': 'application/json'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['success'])

    def test_refill_route_validates_lbs_added(self):
        import hopper
        import web_interface
        client = web_interface.app.test_client()
        hopper.record_dispense(10)
        for bad in ('abc', '0', '-2', '700', 'nan', 'inf'):
            r = client.post('/refill', data={'remaining_pct': '25', 'lbs_added': bad},
                            headers={'Accept': 'application/json'})
            self.assertEqual(r.status_code, 400, bad)
        # A rejected weight must not have recorded the refill
        self.assertEqual(hopper.load_state()['cups_since_refill'], 10)
        r = client.post('/refill', data={'remaining_pct': '25', 'lbs_added': ' 2.5 '},
                        headers={'Accept': 'application/json'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(hopper.cups_per_lb(hopper.load_state()), 4.0)

    def test_refill_route_treats_blank_lbs_as_unweighed(self):
        import hopper
        import web_interface
        client = web_interface.app.test_client()
        hopper.record_dispense(10)
        r = client.post('/refill', data={'remaining_pct': '25', 'lbs_added': ''},
                        headers={'Accept': 'application/json'})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(hopper.cups_per_lb(hopper.load_state()))


if __name__ == '__main__':
    unittest.main()


class TestEventJournal(TempCwd):
    """feeding_events.jsonl: the durable per-event record."""

    def test_dispense_event_carries_numbers_and_hopper_counter(self):
        import events
        with patch('feeder_core.trigger_servo', return_value=0.31), \
             patch('feeder_core.notify.send'):
            feeder_core.feed_pet(portion='medium', base_time='07:00', scheduled_for='07:28')
        (ev,) = events.read_all()
        self.assertEqual(ev['event'], 'dispense')
        self.assertEqual(ev['portion'], 'medium')
        self.assertEqual(ev['cups'], feeding_stats.PORTION_CUPS['medium'])
        self.assertEqual(ev['source'], 'scheduled')
        self.assertEqual(ev['duration_s'], 0.31)
        self.assertEqual((ev['base_time'], ev['scheduled_for']), ('07:00', '07:28'))
        self.assertEqual(ev['hopper_cups'], feeding_stats.PORTION_CUPS['medium'])
        self.assertTrue(ev['sim'])  # test box has no GPIO — analysis must be able to filter this
        datetime.fromisoformat(ev['ts'])

    def test_manual_dispense_has_no_schedule_times(self):
        import events
        with patch('feeder_core.trigger_servo', return_value=0.2), \
             patch('feeder_core.notify.send'):
            feeder_core.feed_pet(portion='small', source='manual')
        (ev,) = events.read_all()
        self.assertEqual(ev['source'], 'manual')
        self.assertIsNone(ev['base_time'])
        self.assertIsNone(ev['scheduled_for'])

    def test_failure_event_records_error(self):
        import events
        with patch('feeder_core.trigger_servo', side_effect=RuntimeError("jam")), \
             patch('feeder_core.notify.send'):
            feeder_core.feed_pet(portion='large', source='manual')
        (ev,) = events.read_all()
        self.assertEqual(ev['event'], 'failure')
        self.assertEqual(ev['error'], 'jam')
        self.assertEqual(ev['portion'], 'large')

    def test_refill_event_records_estimate(self):
        import events, hopper
        for _ in range(4):
            hopper.record_dispense(2.5)
        hopper.record_refill(25)
        ev = events.read_all()[-1]
        self.assertEqual(ev['event'], 'refill')
        self.assertEqual(ev['remaining_pct'], 25)
        self.assertEqual(ev['cups_before'], 10.0)
        self.assertEqual(ev['capacity_estimate'], 13.33)
        self.assertEqual(ev['capacity'], 13.33)

    def test_refill_after_trivial_consumption_records_no_estimate(self):
        import events, hopper
        hopper.record_dispense(0.5)
        hopper.record_refill(50)
        ev = events.read_all()[-1]
        self.assertIsNone(ev['capacity_estimate'])
        self.assertIsNone(ev['capacity'])

    def test_low_event_written_once_per_cycle(self):
        import events, hopper
        with open(hopper.HOPPER_FILE, 'w') as f:
            # 7 of 8 cups gone → level 0.125 (exact in binary, so days_left is a clean 2)
            json.dump({'last_refill': '2026-01-01', 'cups_since_refill': 7.0,
                       'capacity_estimates': [8.0], 'low_notified': False}, f)
        self.assertIsNotNone(hopper.check_low(daily_avg_cups=0.5))
        self.assertIsNone(hopper.check_low(daily_avg_cups=0.5))
        lows = [e for e in events.read_all() if e['event'] == 'hopper_low']
        self.assertEqual(len(lows), 1)
        self.assertEqual(lows[0]['level'], 0.12)
        self.assertEqual(lows[0]['days_left'], 2)

    def test_write_failure_does_not_break_feeding(self):
        import events
        with patch('events.open', side_effect=OSError("disk full")), \
             patch('feeder_core.trigger_servo', return_value=0.2), \
             patch('feeder_core.notify.send'):
            self.assertTrue(feeder_core.feed_pet())

    def test_read_all_skips_malformed_lines(self):
        import events
        events.record('dispense', portion='small')
        with open(events.EVENTS_FILE, 'a') as f:
            f.write('not json\n')
        events.record('refill', remaining_pct=10)
        self.assertEqual([e['event'] for e in events.read_all()], ['dispense', 'refill'])

    def test_missing_file_reads_empty(self):
        import events
        self.assertEqual(events.read_all(), [])

    def test_unserializable_field_does_not_break_feeding(self):
        import events
        with patch('feeder_core.trigger_servo', return_value=object()), \
             patch('feeder_core.notify.send'):
            self.assertTrue(feeder_core.feed_pet())
        (ev,) = events.read_all()
        self.assertIsNone(ev['duration_s'])


class TestRenderNote(TempCwd):
    """ops/mini-sync/render_note.py: merging the journal with log archives."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ops', 'mini-sync', 'render_note.py')
        spec = importlib.util.spec_from_file_location('render_note', path)
        cls.rn = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.rn)

    LOG = [
        "2026-09-10 06:00:00,689 - INFO - Feeding completed in 0.31s (small portion, scheduled)\n",
        "2026-09-10 14:00:01,100 - INFO - Feeding completed in 0.31s (small portion, scheduled)\n",
        "2026-09-10 15:30:00,000 - INFO - Feeding failed (large portion, manual): jam\n",
    ]
    JOURNAL = [
        {'ts': '2026-09-10T14:00:00', 'event': 'dispense', 'portion': 'small', 'cups': 0.25, 'source': 'scheduled'},
        {'ts': '2026-09-10T16:00:00', 'event': 'dispense', 'portion': 'medium', 'cups': 0.5, 'source': 'manual'},
        {'ts': '2026-09-10T16:00:05', 'event': 'dispense', 'portion': 'small', 'cups': 0.25, 'source': 'manual', 'sim': True},
    ]

    def test_overlap_day_is_deduplicated_not_double_counted(self):
        merged = self.rn.merge_dispenses(self.JOURNAL[:2], self.LOG)
        self.assertEqual([(d['ts'].strftime('%H:%M'), d['origin']) for d in merged],
                         [('06:00', 'log'), ('14:00', 'journal'), ('16:00', 'journal')])

    def test_sim_events_are_ignored(self):
        with open('feeding_events.jsonl', 'w') as f:
            for ev in self.JOURNAL:
                f.write(json.dumps(ev) + '\n')
        events = self.rn.load_events('feeding_events.jsonl')
        self.assertEqual(len(events), 2)

    def test_daily_totals_count_manual(self):
        merged = self.rn.merge_dispenses(self.JOURNAL[:2], self.LOG)
        day = self.rn.daily_totals(merged)[date(2026, 9, 10)]
        self.assertEqual((day['cups'], day['feedings'], day['manual']), (1.0, 3, 1))

    def test_render_includes_hopper_and_log_failure(self):
        merged = self.rn.merge_dispenses(self.JOURNAL[:2], self.LOG)
        hopper = {'cups_since_refill': 13.71, 'capacity_estimates': [39.17], 'last_refill': '2026-08-19'}
        text = self.rn.render(merged, self.JOURNAL[:2], hopper,
                              self.rn.failures_from_log(self.LOG), now=datetime(2026, 9, 10, 17))
        self.assertIn('~65% full', text)
        self.assertIn('feeding FAILED (large, manual)', text)
        self.assertIn('| 2026-09-10 | 1 | 3 | 1 |', text)

    def test_render_with_nothing_does_not_crash(self):
        text = self.rn.render([], [], {}, now=datetime(2026, 9, 10, 17))
        self.assertIn('learning capacity', text)
        self.assertIn('No feedings recorded yet', text)


class TestScheduleStore(TempCwd):
    """feeding_schedules.txt round-trips and crash-safe writes."""

    def test_round_trip_normalizes_legacy_lines(self):
        import schedule_store
        with open('feeding_schedules.txt', 'w') as f:
            f.write("08:00,fixed\n\n 12:00 , large \n")
        schedule_store.write_entries(schedule_store.read_entries())
        with open('feeding_schedules.txt') as f:
            self.assertEqual(f.read(), "08:00,small,fixed\n12:00,large\n")

    def test_missing_file_reads_empty(self):
        import schedule_store
        self.assertEqual(schedule_store.read_entries(), [])

    def test_failed_write_leaves_original_and_no_debris(self):
        # The power-cut case: if the swap never happens, the old file survives intact
        import atomicfile
        with open('state.txt', 'w') as f:
            f.write("original")
        with patch('atomicfile.os.replace', side_effect=OSError("power cut")):
            with self.assertRaises(OSError):
                atomicfile.write_atomic('state.txt', "new")
        with open('state.txt') as f:
            self.assertEqual(f.read(), "original")
        self.assertEqual(os.listdir('.'), ['state.txt'])

    def test_missing_schedule_file_pages(self):
        with patch('feeder_core.notify.send') as mock_send:
            self.assertEqual(feeder_core.generate_todays_schedule(), [])
        self.assertIn("No feedings", mock_send.call_args[0][0])
        self.assertTrue(os.path.isfile('feeding_schedules.txt'))

    def test_nonempty_schedule_does_not_page(self):
        with open('feeding_schedules.txt', 'w') as f:
            f.write("08:00,small,fixed\n")
        with patch('feeder_core.notify.send') as mock_send:
            feeder_core.generate_todays_schedule()
        mock_send.assert_not_called()


class TestScheduleRoutes(TempCwd):
    def setUp(self):
        super().setUp()
        schedule.clear()
        import web_interface
        self.client = web_interface.app.test_client()
        self.json = {'Accept': 'application/json'}

    def tearDown(self):
        schedule.clear()
        super().tearDown()

    def _file(self):
        with open('feeding_schedules.txt') as f:
            return f.read()

    def test_add_rejects_malformed_time_without_writing(self):
        for bad in ['7:5', '25:00', 'noon', '']:
            resp = self.client.post('/add', data={'feeding_time': bad}, headers=self.json)
            self.assertEqual(resp.status_code, 400, bad)
        self.assertFalse(os.path.exists('feeding_schedules.txt'))

    def test_add_then_duplicate_conflicts(self):
        resp = self.client.post('/add', data={'feeding_time': '23:58', 'portion': 'large'},
                                headers=self.json)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._file(), "23:58,large,fixed\n")
        resp = self.client.post('/add', data={'feeding_time': '23:58'}, headers=self.json)
        self.assertEqual(resp.status_code, 409)

    def test_toggle_legacy_fixed_line_randomizes_it(self):
        with open('feeding_schedules.txt', 'w') as f:
            f.write("08:00,fixed\n")
        self.client.post('/toggle_fixed', data={'base_time': '08:00'}, headers=self.json)
        self.assertEqual(self._file(), "08:00,small\n")

    def test_toggle_unknown_time_is_404(self):
        resp = self.client.post('/toggle_fixed', data={'base_time': '09:00'}, headers=self.json)
        self.assertEqual(resp.status_code, 404)

    def test_update_portion_and_delete(self):
        with open('feeding_schedules.txt', 'w') as f:
            f.write("08:00,small,fixed\n12:00,small\n")
        self.client.post('/update_portion', data={'base_time': '08:00', 'portion': 'large'},
                         headers=self.json)
        self.client.post('/delete', data={'base_time': '12:00'}, headers=self.json)
        self.assertEqual(self._file(), "08:00,large,fixed\n")


class TestLearnedCupsPerLb(unittest.TestCase):
    def test_consumption_uses_learned_ratio(self):
        week = [{'total_cups': 2.0, 'total_feedings': 4}]
        self.assertEqual(feeding_stats.calculate_consumption_rate(week)['daily_lbs'], 0.5)
        self.assertEqual(feeding_stats.calculate_consumption_rate(
            week, cups_per_lb=5.0)['daily_lbs'], 0.4)


class TestManualFeedGuards(TempCwd):
    def setUp(self):
        super().setUp()
        import web_interface
        self.wi = web_interface
        web_interface._last_manual_feed = None
        self.client = web_interface.app.test_client()
        self.json = {'Accept': 'application/json'}
        with open('feeding_schedules.txt', 'w') as f:
            f.write("08:00,medium\n17:00,medium\n20:00,small\n")  # 1.25 cups → allowance 0.75 (floor)

    def _log_manual(self, portion, n):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('feeding_log.txt', 'a') as f:
            for _ in range(n):
                f.write(f"{stamp},100 - INFO - Feeding completed in 0.31s ({portion} portion, manual)\n")

    def test_allowance_is_half_schedule_with_floor(self):
        self.assertEqual(self.wi.manual_allowance_cups(), 0.75)
        with open('feeding_schedules.txt', 'w') as f:
            f.write("06:00,large\n12:00,large\n18:00,large\n")  # 2.25 cups
        self.assertEqual(self.wi.manual_allowance_cups(), 1.125)

    def test_feed_within_allowance_dispenses(self):
        with patch('web_interface.feed_pet', return_value=True) as mock_feed:
            resp = self.client.post('/feed', data={'portion': 'small'}, headers=self.json)
        self.assertEqual(resp.status_code, 200)
        mock_feed.assert_called_once()

    def test_feed_over_allowance_refused_without_dispensing(self):
        self._log_manual('medium', 1)  # 0.5 used; a medium would make 1.0 > 0.75
        with patch('web_interface.feed_pet') as mock_feed:
            resp = self.client.post('/feed', data={'portion': 'medium'}, headers=self.json)
        self.assertEqual(resp.status_code, 429)
        self.assertIn('0.5 of 0.75', resp.get_json()['message'])
        mock_feed.assert_not_called()

    def test_scheduled_feeds_do_not_count_toward_manual_cap(self):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('feeding_log.txt', 'w') as f:
            f.write(f"{stamp},1 - INFO - Feeding completed in 0.3s (large portion, scheduled)\n" * 3)
        with patch('web_interface.feed_pet', return_value=True):
            resp = self.client.post('/feed', data={'portion': 'small'}, headers=self.json)
        self.assertEqual(resp.status_code, 200)

    def test_second_feed_within_cooldown_refused(self):
        with patch('web_interface.feed_pet', return_value=True) as mock_feed:
            self.client.post('/feed', data={'portion': 'small'}, headers=self.json)
            resp = self.client.post('/feed', data={'portion': 'small'}, headers=self.json)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(mock_feed.call_count, 1)

    def test_failed_feed_does_not_start_cooldown(self):
        with patch('web_interface.feed_pet', side_effect=[False, True]) as mock_feed:
            self.client.post('/feed', data={'portion': 'small'}, headers=self.json)
            resp = self.client.post('/feed', data={'portion': 'small'}, headers=self.json)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_feed.call_count, 2)

    def test_cross_origin_post_refused(self):
        with patch('web_interface.feed_pet') as mock_feed:
            resp = self.client.post('/feed', data={'portion': 'small'},
                                    headers={**self.json, 'Origin': 'https://evil.example'})
        self.assertEqual(resp.status_code, 403)
        mock_feed.assert_not_called()

    def test_same_origin_and_originless_posts_allowed(self):
        with patch('web_interface.feed_pet', return_value=True):
            resp = self.client.post('/feed', data={'portion': 'small'},
                                    headers={**self.json, 'Origin': 'http://localhost'})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/add', data={'feeding_time': '23:59'}, headers=self.json)
        self.assertEqual(resp.status_code, 200)


class TestWatchdog(TempCwd):
    """ops/mini-sync/watchdog.py: outside-in alerts from the synced store."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ops', 'mini-sync', 'watchdog.py')
        spec = importlib.util.spec_from_file_location('watchdog', path)
        cls.wd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.wd)

    NOW = datetime(2026, 9, 29, 14, 30)

    def _store(self, schedule_date='2026-09-29', times=('06:00', '14:00'), events=()):
        with open('todays_schedule.json', 'w') as f:
            json.dump({'date': schedule_date, 'schedule': [
                {'base_time': t, 'actual_time': t, 'portion': 'small'} for t in times]}, f)
        with open('feeding_events.jsonl', 'w') as f:
            for e in events:
                f.write(json.dumps(e) + '\n')

    @staticmethod
    def _dispense(time_str, **extra):
        return {'ts': f'2026-09-29T{time_str}:01', 'event': 'dispense', 'scheduled_for': time_str, **extra}

    def _keys(self, now=None, contact_ago=5):
        alerts, _ = self.wd.check('.', now or self.NOW, (now or self.NOW) - timedelta(minutes=contact_ago))
        return [k for k, _, _ in alerts]

    def test_all_fed_is_quiet(self):
        self._store(events=[self._dispense('06:00'), self._dispense('14:00')])
        self.assertEqual(self._keys(), [])

    def test_missed_feed_after_grace_alerts(self):
        self._store(events=[self._dispense('06:00')])
        self.assertEqual(self._keys(), ['missed:2026-09-29:14:00'])

    def test_missed_feed_within_grace_is_quiet(self):
        self._store(events=[self._dispense('06:00')])
        self.assertEqual(self._keys(now=datetime(2026, 9, 29, 14, 10)), [])

    def test_failure_event_is_not_double_paged(self):
        self._store(events=[self._dispense('06:00'),
                            {'ts': '2026-09-29T14:00:01', 'event': 'failure', 'scheduled_for': '14:00'}])
        self.assertEqual(self._keys(), [])

    def test_unrolled_schedule_alerts_after_grace(self):
        self._store(schedule_date='2026-09-28')
        self.assertEqual(self._keys(), ['stale:2026-09-29'])
        self.assertEqual(self._keys(now=datetime(2026, 9, 29, 0, 5)), [])

    def test_sim_events_from_pi_alert(self):
        self._store(events=[self._dispense('06:00', sim=True), self._dispense('14:00', sim=True)])
        self.assertEqual(self._keys(), ['sim:2026-09-29'])

    def test_no_contact_is_unreachable(self):
        alerts, reachable = self.wd.check('.', self.NOW, None)
        self.assertFalse(reachable)
        self.assertEqual([k for k, _, _ in alerts], ['unreachable'])

    def test_stale_data_skips_schedule_checks(self):
        self._store(events=[])  # everything "missed", but data is 30 min old
        self.assertEqual(self._keys(contact_ago=30), [])

    def test_alerts_once_then_recovery_notice(self):
        with open('last_contact', 'w') as f:
            f.write(str(int((datetime.now() - timedelta(hours=2)).timestamp())))
        with patch.object(self.wd, 'send', return_value=True) as mock_send, \
             patch.object(self.wd.sys, 'argv', ['watchdog.py', '.']):
            self.wd.main()
            self.wd.main()
            self.assertEqual(mock_send.call_count, 1)
            with open('last_contact', 'w') as f:
                f.write(str(int(datetime.now().timestamp())))
            self._store(schedule_date=date.today().isoformat(), times=())
            self.wd.main()
            self.assertEqual(mock_send.call_args[0][0], "Feeder is back online.")

    def test_unsent_alert_is_retried(self):
        with patch.object(self.wd, 'send', return_value=False) as mock_send, \
             patch.object(self.wd.sys, 'argv', ['watchdog.py', '.']):
            self.wd.main()
            self.wd.main()
        self.assertEqual(mock_send.call_count, 2)


class TestGpioLoading(unittest.TestCase):
    def test_off_pi_missing_gpio_simulates(self):
        import DRV8825
        _, sim = DRV8825.load_gpio(force_simulate=False, is_pi=False)
        self.assertTrue(sim)  # RPi.GPIO isn't installed on the dev box

    def test_on_pi_missing_gpio_refuses_to_simulate(self):
        import DRV8825
        with self.assertRaises(ImportError):
            DRV8825.load_gpio(force_simulate=False, is_pi=True)

    def test_forced_simulation_wins_on_pi(self):
        import DRV8825
        _, sim = DRV8825.load_gpio(force_simulate=True, is_pi=True)
        self.assertTrue(sim)
