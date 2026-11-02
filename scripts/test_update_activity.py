from datetime import date, datetime, timedelta, timezone
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree

from update_activity import main, parse_calendar, summarize, render_stats, render_calendar


def fixture(counts=None):
    counts = counts or [0] * 365
    start = date(2025, 10, 28)
    cells, tips = [], []
    for i, count in enumerate(counts):
        cells.append(f'<td id="day-{i}" data-date="{start + timedelta(days=i)}" data-level="{min(count, 4)}"></td>')
        prefix = "No contributions" if count == 0 else f'{count} contribution{"s" if count != 1 else ""}'
        tips.append(f'<tool-tip for="day-{i}">{prefix} on October 28th.</tool-tip>')
    return f'<h2 id="js-contribution-activity-description">{sum(counts):,} contributions in the last year</h2>' + "".join(cells + tips)


class ActivityTest(unittest.TestCase):
    def test_public_calendar_counts_match_header(self):
        days = parse_calendar(fixture([0] * 360 + [1, 2, 0, 4, 1]))
        self.assertEqual(len(days), 365)
        self.assertEqual(summarize(days, days[-1][0]), (8, 4, 2, 2))

    def test_today_has_until_midnight_to_continue(self):
        today = date(2026, 10, 27)
        days = [(today - timedelta(days=3-i), count, min(count, 4)) for i, count in enumerate([0, 2, 7, 0])]
        self.assertEqual(summarize(days, today), (9, 2, 2, 2))
        self.assertEqual(summarize(days, today + timedelta(days=1))[2], 0)

    def test_weekend_is_a_gap_and_best_run_is_separate(self):
        days = parse_calendar(fixture([0] * 354 + [1] * 5 + [0, 0, 1, 1, 1, 0]))
        self.assertEqual(summarize(days, days[-1][0]), (8, 8, 3, 5))

    def test_missing_tooltip_does_not_publish_zero(self):
        with self.assertRaisesRegex(ValueError, "missing day counts"):
            parse_calendar(fixture().replace('for="day-0"', 'for="missing"'))

    def test_changed_total_or_layout_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "displayed total"):
            parse_calendar(fixture().replace("0 contributions in the last year", "99 contributions in the last year"))
        with self.assertRaises(ValueError):
            parse_calendar("<html>Temporarily unavailable</html>")

    def test_missing_and_duplicate_dates_are_rejected(self):
        for replacement in ["2025-10-28", "2025-10-30"]:
            with self.assertRaisesRegex(ValueError, "duplicated or incomplete"):
                parse_calendar(fixture().replace('data-date="2025-10-29"', f'data-date="{replacement}"'))

    def test_inconsistent_response_retries_then_publishes_verified_data(self):
        valid = fixture([0] * 364 + [3])
        invalid = valid.replace("3 contributions in the last year", "4 contributions in the last year")
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            responses = []
            for html in (invalid, valid):
                response = MagicMock()
                response.__enter__.return_value.read.return_value = html.encode()
                responses.append(response)
            with patch("update_activity.ASSETS", assets), patch("update_activity.datetime") as clock, patch("update_activity.urlopen", side_effect=responses) as request, patch("update_activity.sleep") as sleep, redirect_stdout(StringIO()):
                clock.now.return_value = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
                main()
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once_with(1)
            self.assertIn("3 contributions", (assets / "activity.svg").read_text())
            self.assertIn("2026-10-27: 3 contributions", (assets / "calendar.svg").read_text())

    def test_repeated_total_mismatch_keeps_existing_cards_with_warning(self):
        html = fixture().replace("0 contributions in the last year", "99 contributions in the last year")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = html.encode()
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            for name in ("activity.svg", "calendar.svg"):
                (assets / name).write_text("last verified card")
            output = StringIO()
            with patch("update_activity.ASSETS", assets), patch("update_activity.datetime") as clock, patch("update_activity.urlopen", return_value=response) as request, patch("update_activity.sleep") as sleep, redirect_stdout(output):
                clock.now.return_value = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
                main()
            self.assertEqual(request.call_count, 3)
            self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])
            self.assertIn("::warning::", output.getvalue())
            for name in ("activity.svg", "calendar.svg"):
                self.assertEqual((assets / name).read_text(), "last verified card")

    def test_malformed_calendar_still_fails_without_overwriting_cards(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>Incomplete calendar</html>"
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            (assets / "activity.svg").write_text("last verified card")
            with patch("update_activity.ASSETS", assets), patch("update_activity.urlopen", return_value=response) as request, patch("update_activity.sleep") as sleep:
                with self.assertRaisesRegex(ValueError, "missing day counts"):
                    main()
            request.assert_called_once()
            sleep.assert_not_called()
            self.assertEqual((assets / "activity.svg").read_text(), "last verified card")
            self.assertFalse((assets / "calendar.svg").exists())

    def test_render_is_accessible_svg_without_external_services(self):
        days = parse_calendar(fixture())
        now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        for svg in [render_stats(days, now), render_calendar(days, now)]:
            root = ElementTree.fromstring(svg)
            self.assertEqual(root.attrib["role"], "img")
            self.assertIsNotNone(root.find("{http://www.w3.org/2000/svg}desc"))
            self.assertNotIn("<script", svg)
            self.assertNotIn("<image", svg)
            self.assertNotIn("demolab", svg)


if __name__ == "__main__":
    unittest.main()
