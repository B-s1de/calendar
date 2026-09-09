import re
import pathlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
from icalendar import Calendar, Event
from zoneinfo import ZoneInfo

SEMESTER_URL = "https://timetable.spbu.ru/PSYC/StudentGroupEvents/Semester/459496?lang=ru"
OUT = "site/spbu.ics"
TZ = ZoneInfo("Europe/Moscow")

DAYS = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

def fetch_lines():
    r = requests.get(
        SEMESTER_URL,
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 SPbU-iCalendar/1.0"},
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]

def parse_date_token(token, semester_year=2026):
    """Return all dates represented by a token such as 21.12 or 07.09–14.09."""
    token = token.replace("–", "-").replace("—", "-").strip()
    token = re.sub(r"\s*\(\d+\)\s*$", "", token)

    m = re.fullmatch(r"(\d{2})\.(\d{2})", token)
    if m:
        return [date(semester_year, int(m.group(2)), int(m.group(1)))]

    m = re.fullmatch(r"(\d{2})\.(\d{2})-(\d{2})\.(\d{2})", token)
    if m:
        d1, m1, d2, m2 = map(int, m.groups())
        start = date(semester_year, m1, d1)
        end = date(semester_year, m2, d2)
        return [start + timedelta(days=i) for i in range((end-start).days + 1)]

    return []

def dates_for_day_spec(spec, weekday, semester_year=2026):
    dates = parse_date_token(spec, semester_year)
    return [d for d in dates if d.weekday() == weekday]

def main():
    lines = fetch_lines()
    events = []

    current_weekday = None
    i = 0

    time_re = re.compile(r"^(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})$")
    date_re = re.compile(
        r"^(?:\d{2}\.\d{2})(?:[–-]\d{2}\.\d{2})?(?:\s*\(\d+\))?$"
    )

    while i < len(lines):
        line = lines[i]

        if line in DAYS:
            current_weekday = DAYS[line]
            i += 1
            continue

        tm = time_re.match(line)
        if not tm or current_weekday is None:
            i += 1
            continue

        sh, sm, eh, em = map(int, tm.groups())

        # Immediately after a time SPbU lists one or more date specifications.
        specs = []
        j = i + 1
        while j < len(lines) and date_re.match(lines[j]):
            specs.append(lines[j])
            j += 1

        # Then comes subject, followed by cohort/location/teacher information.
        if j >= len(lines):
            break

        subject = lines[j]
        j += 1

        extras = []
        while j < len(lines):
            x = lines[j]
            if x in DAYS or time_re.match(x) or date_re.match(x):
                break
            # Semester page sometimes repeats navigation labels.
            if x not in {
                "All classes", "online courses",
                "interim attestation", "final attestation",
                "autumn semester", "spring term ›", "to week"
            }:
                extras.append(x)
            j += 1

        location_parts = []
        teacher = ""
        cohort = ""
        for x in extras:
            if x == "Online teaching":
                location_parts.append(x)
            elif x.startswith(("naberezhnaya ", "Naberezhnaya ")):
                location_parts.append(x)
            elif x.startswith("Cohort "):
                cohort = x
            elif re.fullmatch(r"[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)*\.?", x):
                teacher = x

        location = "; ".join(dict.fromkeys(location_parts))
        description_parts = []
        if cohort:
            description_parts.append(cohort)
        if teacher:
            description_parts.append("Teacher: " + teacher)

        for spec in specs:
            for d in dates_for_day_spec(spec, current_weekday):
                events.append({
                    "date": d,
                    "sh": sh, "sm": sm, "eh": eh, "em": em,
                    "subject": subject,
                    "location": location,
                    "description": "\n".join(description_parts),
                })

        i = j

    # Remove exact duplicates.
    unique = {}
    for e in events:
        key = (
            e["date"], e["sh"], e["sm"], e["eh"], e["em"],
            e["subject"], e["location"], e["description"]
        )
        unique[key] = e

    cal = Calendar()
    cal.add("prodid", "-//SPbU 26.M05-ps Timetable//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "СПбГУ — 26.М05-пс")
    cal.add("x-wr-timezone", "Europe/Moscow")
    cal.add("refresh-interval;value=duration", "PT6H")
    cal.add("x-published-ttl", "PT6H")

    for e in sorted(unique.values(), key=lambda x: (
        x["date"], x["sh"], x["sm"], x["subject"]
    )):
        ev = Event()
        safe_subject = re.sub(r"[^A-Za-z0-9А-Яа-я]+", "-", e["subject"])[:70]
        uid = (
            f'{e["date"].isoformat()}-{e["sh"]:02d}{e["sm"]:02d}-'
            f'{safe_subject}@spbu-459496'
        )
        ev.add("uid", uid)
        ev.add(
            "dtstart",
            datetime(
                e["date"].year, e["date"].month, e["date"].day,
                e["sh"], e["sm"], tzinfo=TZ
            ),
        )
        ev.add(
            "dtend",
            datetime(
                e["date"].year, e["date"].month, e["date"].day,
                e["eh"], e["em"], tzinfo=TZ
            ),
        )
        ev.add("summary", e["subject"])
        if e["location"]:
            ev.add("location", e["location"])
        if e["description"]:
            ev.add("description", e["description"])
        ev.add("dtstamp", datetime.now(TZ))
        cal.add_component(ev)

    out = pathlib.Path(OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(cal.to_ical())
    print(f"Parsed {len(unique)} calendar events")
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
