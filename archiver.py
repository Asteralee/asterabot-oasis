import os
import re
import time
import requests
import datetime
import mwparserfromhell

API = "https://test.wikipedia.org/w/api.php"
session = requests.Session()

USERNAME = os.environ["BOT_USER"]
PASSWORD = os.environ["BOT_PASS"]


def login():
    token = session.get(API, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }).json()["query"]["tokens"]["logintoken"]

    session.post(API, data={
        "action": "login",
        "lgname": USERNAME,
        "lgpassword": PASSWORD,
        "lgtoken": token,
        "format": "json"
    })


def get_watchlist():
    r = session.get(API, params={
        "action": "query",
        "list": "watchlistraw",
        "wrlimit": "max",
        "format": "json"
    }).json()

    return [p["title"] for p in r["query"]["watchlistraw"]]


def get_page(title):
    r = session.get(API, params={
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "titles": title,
        "format": "json"
    }).json()

    pages = r["query"]["pages"]
    return next(iter(pages.values()))["revisions"][0]["*"]


def edit_page(title, text, summary):
    token = session.get(API, params={
        "action": "query",
        "meta": "tokens",
        "format": "json"
    }).json()["query"]["tokens"]["csrftoken"]

    session.post(API, data={
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "format": "json"
    })

def parse_ago(value):
    m = re.match(r"^\s*(\d+)\s*([mdhw])\s*$", value.lower())
    if not m:
        raise ValueError(f"Invalid ago format: {value}")

    n = int(m.group(1))
    unit = m.group(2)

    return n * {
        "m": 1/60,
        "h": 1,
        "d": 24,
        "w": 168
    }[unit]


def resolve(pattern, title):
    now = datetime.datetime.utcnow()
    return (
        pattern
        .replace("%(fullpage)", title)
        .replace("%(year)", str(now.year))
    )

def get_config(text):
    code = mwparserfromhell.parse(text)

    for t in code.filter_templates():
        if t.name.matches("Autoarchive"):
            archive = str(t.get("archive").value).strip()
            ago = str(t.get("ago").value).strip()
            return archive, parse_ago(ago)

    return None, None

def split_sections(text):
    parts = re.split(r"(==.*?==)", text)
    lead = parts[0]

    sections = [
        (parts[i], parts[i+1] if i+1 < len(parts) else "")
        for i in range(1, len(parts), 2)
    ]

    return lead, sections

def has_marker(section_text):
    return bool(re.search(r'discussion-archived', section_text, re.I))

TIMESTAMP = r"\d{2}:\d{2}, \d{1,2} \w+ \d{4}"


def latest_ts(text):
    matches = re.findall(TIMESTAMP, text)

    ts = []
    for m in matches:
        try:
            ts.append(datetime.datetime.strptime(m, "%H:%M, %d %B %Y"))
        except:
            pass

    return max(ts).replace(tzinfo=datetime.timezone.utc) if ts else None


def old_enough(text, hours):
    ts = latest_ts(text)
    if not ts:
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - ts).total_seconds() / 3600 >= hours

def process(title):
    text = get_page(title)

    pattern, hours = get_config(text)
    if not pattern:
        return

    archive_title = resolve(pattern, title)

    lead, sections = split_sections(text)

    keep, move = [], []

    for h, b in sections:
        full = h + b

        if has_marker(full) and old_enough(full, hours):
            move.append(full)
        else:
            keep.append(full)

    if not move:
        return

    new_main = lead + "".join(keep)

    try:
        archive_text = get_page(archive_title)
    except:
        archive_text = ""

    archive_text += "\n\n" + "\n\n".join(move)

    edit_page(archive_title, archive_text, "Bot: archiving sections")
    edit_page(title, new_main, "Bot: removing archived sections")

def run():
    login()

    for title in get_watchlist():
        try:
            print("Processing:", title)
            process(title)
            time.sleep(3)
        except Exception as e:
            print("Error:", title, e)


if __name__ == "__main__":
    run()
