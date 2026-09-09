import re
import pathlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from icalendar import Calendar, Event
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

GROUP_URL = "https://timetable.spbu.ru/PSYC/StudentGroupEvents/Primary/459496"
BASE = "https://timetable.spbu.ru"
OUT = "site/spbu.ics"
TZ = ZoneInfo("Europe/Moscow")

def get_soup(url):
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def parse_week(url):
    soup = get_soup(url)
    # Page structure: day heading -> time -> title -> location -> teacher.
    events = []
    current_date = None
    for node in soup.find_all(["h4", "p", "div", "li"]):
        text = " ".join(node.stripped_strings)
        if not text:
            continue
        m = re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Z][a-z]+)\s+(\d{1,2})$", text)
        if m:
            month = datetime.strptime(m.group(2), "%B").month
            year = datetime.now(TZ).year
            current_date = datetime(year, month, int(m.group(3))).date()
    # More robustly parse the visible text blocks using headings and time patterns.
    lines = [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]
    current_date = None
    i = 0
    while i < len(lines):
        line = lines[i]
        dm = re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Z][a-z]+)\s+(\d{1,2})$", line)
        if dm:
            year = datetime.now(TZ).year
            current_date = datetime(year, datetime.strptime(dm.group(2), "%B").month, int(dm.group(3))).date()
            i += 1
            continue
        tm = re.match(r"^(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})$", line)
        if tm and current_date:
            sh, sm, eh, em = map(int, tm.groups())
            # Following lines contain subject, optional cohort, location and teacher.
            chunk = []
            j = i + 1
            while j < len(lines) and not re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),", lines[j]) and not re.match(r"^\d{1,2}:\d{2}[–-]\d{1,2}:\d{2}$", lines[j]):
                if lines[j] not in ("All classes", "online courses", "interim attestation", "final attestation"):
                    chunk.append(lines[j])
                j += 1
            if chunk:
                subject = chunk[0]
                extras = chunk[1:]
                location = ""
                teacher = ""
                for x in extras:
                    if x == "Online teaching":
                        location = x
                    elif not teacher and re.match(r"^[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)*\.?$", x):
                        teacher = x
                    elif x.startswith(("naberezhnaya ", "Naberezhnaya ")):
                        location = x
                # Keep cohort information in description.
                desc = "\n".join(x for x in extras if x not in (location, teacher))
                events.append((current_date, sh, sm, eh, em, subject, location, teacher, desc))
            i = j
            continue
        i += 1
    return events

def main():
    # Fetch the semester view if available; otherwise start from the current page
    soup = get_soup(GROUP_URL)
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        if "StudentGroupEvents" in href and "weekMonday" in href:
            links.append(href)
    links = list(dict.fromkeys(links))
    # Current page is always included.
    if not links:
        links = [GROUP_URL]

    all_events = []
    for url in links:
        try:
            all_events.extend(parse_week(url))
        except Exception as e:
            print(f"Warning: {url}: {e}")

    # De-duplicate.
    seen = set()
    unique = []
    for e in all_events:
        key = e[:6] + (e[6],)
        if key not in seen:
            seen.add(key)
            unique.append(e)

    cal = Calendar()
    cal.add("prodid", "-//SPbU Timetable to iCalendar//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "СПбГУ — 26.М05-пс")
    cal.add("x-wr-timezone", "Europe/Moscow")
    cal.add("refresh-interval;value=duration", "PT6H")
    cal.add("x-published-ttl", "PT6H")

    for date, sh, sm, eh, em, subject, location, teacher, desc in unique:
        ev = Event()
        ev.add("uid", f"{date.isoformat()}-{sh:02d}{sm:02d}-{re.sub(r'[^a-zA-Z0-9]+','-',subject)[:60]}@spbu-calendar")
        ev.add("dtstart", datetime(date.year, date.month, date.day, sh, sm, tzinfo=TZ))
        ev.add("dtend", datetime(date.year, date.month, date.day, eh, em, tzinfo=TZ))
        ev.add("summary", subject)
        if location:
            ev.add("location", location)
        if teacher or desc:
            ev.add("description", "\n".join(x for x in (teacher, desc) if x))
        ev.add("dtstamp", datetime.now(TZ))
        cal.add_component(ev)

    out = pathlib.Path(OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(cal.to_ical())
    print(f"Wrote {len(unique)} events to {OUT}")

if __name__ == "__main__":
    main()
