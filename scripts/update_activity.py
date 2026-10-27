"""Refresh profile cards from GitHub's publicly visible contribution calendar."""

from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.request import Request, urlopen

USERNAME = "AhmadHanif12"
SOURCE = f"https://github.com/users/{USERNAME}/contributions"
ASSETS = Path(__file__).resolve().parents[1] / "assets"
COLORS = ["#e6e9e1", "#bdd8c6", "#7bbf9a", "#3b946a", "#176447"]


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self.counts = {}
        self.target = None
        self.in_heading = False
        self.parts = []
        self.heading = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td" and "data-date" in attrs:
            self.cells[attrs["id"]] = (date.fromisoformat(attrs["data-date"]), int(attrs["data-level"]))
        if tag == "tool-tip":
            self.target = attrs.get("for")
            self.parts = []
        if tag == "h2" and attrs.get("id") == "js-contribution-activity-description":
            self.in_heading = True

    def handle_data(self, text):
        if self.target:
            self.parts.append(text)
        if self.in_heading:
            self.heading.append(text)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.target:
            text = " ".join("".join(self.parts).split())
            match = re.fullmatch(r"(No|[\d,]+) contributions? on .+\.", text)
            if match:
                self.counts[self.target] = 0 if match[1] == "No" else int(match[1].replace(",", ""))
            self.target = None
        if tag == "h2":
            self.in_heading = False


def parse_calendar(html):
    # GitHub has no unauthenticated calendar API; fail closed if its HTML changes.
    parser = CalendarParser()
    parser.feed(html)
    if not parser.cells or set(parser.cells) - set(parser.counts):
        raise ValueError("GitHub calendar is missing day counts")
    days = sorted((day, parser.counts[key], level) for key, (day, level) in parser.cells.items())
    if not 350 <= len(days) <= 380:
        raise ValueError("Expected a complete last-year contribution calendar")
    if any(b[0] - a[0] != timedelta(days=1) for a, b in zip(days, days[1:])):
        raise ValueError("Calendar dates are duplicated or incomplete")
    if any(count < 0 or not 0 <= level <= 4 for _, count, level in days):
        raise ValueError("Invalid contribution count or intensity")
    match = re.search(r"([\d,]+)\s+contributions?\s+in the last year", " ".join(parser.heading))
    if not match or int(match[1].replace(",", "")) != sum(count for _, count, _ in days):
        raise ValueError("Day counts do not match GitHub's displayed total")
    return days


def summarize(days, today):
    counts = {day: count for day, count, _ in days}
    current = longest = run = 0
    for _, count, _ in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    end = today if counts.get(today, 0) else today - timedelta(days=1)
    while counts.get(end, 0):
        current += 1
        end -= timedelta(days=1)
    return sum(counts.values()), sum(count > 0 for count in counts.values()), current, longest


def svg_start(width, height, title, description):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>',
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="3" fill="#f5f3ec" stroke="#d9ddd4"/>',
    ]


def label(x, y, text, size=16, color="#17251f", **attrs):
    extra = " ".join(f'{key.replace("_", "-")}="{escape(str(value), quote=True)}"' for key, value in attrs.items())
    return f'<text x="{x}" y="{y}" fill="{color}" font-family="Arial,sans-serif" font-size="{size}" {extra}>{escape(str(text))}</text>'


def render_stats(days, now):
    total, active, current, longest = summarize(days, now.date())
    stamp = now.strftime("%d %b %Y, %H:%M UTC")
    svg = svg_start(600, 338, "GitHub activity", f"GitHub's last-year chart. {total} contributions, {active} active days, current streak {current} days, longest streak in this chart {longest} days. Updated {stamp}.")
    svg += [
        label(28, 35, "GITHUB ACTIVITY", 14, "#23745e", letter_spacing="1.5"),
        label(28, 59, f'{days[0][0]:%d %b %Y} - {days[-1][0]:%d %b %Y}', 14, "#5d6b63"),
        '<path d="M300 84v195M28 185h544" stroke="#d9ddd4"/>',
    ]
    for x, y, value, title, note in [
        (28, 125, total, "Contributions", "in GitHub's last-year chart"),
        (328, 125, active, "Active days", "at least one contribution"),
        (28, 236, current, "Current streak", "consecutive days, including weekends"),
        (328, 236, longest, "Longest streak", "days within this chart"),
    ]:
        svg += [
            label(x, y, f"{value:,}", 40, "#17251f", font_weight="600"),
            label(x, y + 27, title, 17),
            label(x, y + 48, note, 12, "#5d6b63"),
        ]
    svg += [label(28, 315, f"Updated {stamp} · Source: GitHub calendar", 13, "#5d6b63"), "</svg>"]
    return "\n".join(svg) + "\n"


def render_calendar(days, now):
    svg = svg_start(860, 206, "Daily GitHub contributions", "GitHub's publicly visible contribution calendar. Private work is represented only by the anonymous counts GitHub publishes.")
    svg += [label(28, 30, "A YEAR OF BUILDING", 14, "#23745e", letter_spacing="1.5")]
    start = days[0][0] - timedelta(days=(days[0][0].weekday() + 1) % 7)
    for day, count, level in days:
        week, weekday = divmod((day - start).days, 7)
        x, y = 49 + week * 14, 65 + weekday * 14
        if weekday == 0 and day.day <= 7:
            svg.append(label(x, 53, day.strftime("%b"), 12, "#5d6b63"))
        svg.append(f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{COLORS[level]}"><title>{day}: {count} contributions</title></rect>')
    for day, name in [(1, "M"), (3, "W"), (5, "F")]:
        svg.append(label(28, 73 + day * 14, name, 11, "#5d6b63"))
    svg += [
        label(28, 185, f'{days[0][0]:%b %Y} - {days[-1][0]:%b %Y} · GitHub calendar days', 12, "#5d6b63"),
        label(673, 185, "Less", 11, "#5d6b63"),
    ]
    for i, color in enumerate(COLORS):
        svg.append(f'<rect x="{706 + i * 14}" y="175" width="10" height="10" rx="2" fill="{color}"/>')
    svg += [label(780, 185, "More", 11, "#5d6b63"), "</svg>"]
    return "\n".join(svg) + "\n"


def main():
    now = datetime.now(timezone.utc)
    request = Request(SOURCE, headers={
        "User-Agent": f"{USERNAME}-profile-activity",
        "Accept-Language": "en-US",
        "Cache-Control": "no-cache",
    })
    with urlopen(request, timeout=30) as response:
        html = response.read(2_000_001)
    if len(html) > 2_000_000:
        raise ValueError("Unexpectedly large calendar response")
    days = parse_calendar(html.decode("utf-8"))
    if days[-1][0] != now.date():
        raise ValueError("GitHub calendar has not reached the current UTC day")
    stats = render_stats(days, now)
    calendar = render_calendar(days, now)
    # Validate both before replacing either published asset.
    from xml.etree.ElementTree import fromstring
    fromstring(stats)
    fromstring(calendar)
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "activity.svg").write_text(stats, encoding="utf-8")
    (ASSETS / "calendar.svg").write_text(calendar, encoding="utf-8")
    print(dict(zip(("contributions", "active_days", "current_streak", "longest_in_chart"), summarize(days, now.date()))))


if __name__ == "__main__":
    main()
