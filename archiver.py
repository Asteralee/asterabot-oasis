import os
import re
import time
import requests
import datetime
import mwparserfromhell

API = "https://test.wikipedia.org/w/api.php"
session = requests.Session()

session.headers.update({
    "User-Agent": "AutoarchiveBot/1.0"
})

USERNAME = os.environ["BOT_USER"]
PASSWORD = os.environ["BOT_PASS"]

def safe_get(params, retries=3):
    for i in range(retries):
        r = session.get(API, params=params)

        try:
            data = r.json()
        except Exception:
            print("Bad JSON retry", i + 1)
            print(r.text[:200])
            time.sleep(2 * (i + 1))
            continue

        if "error" in data:
            print("API error:", data["error"])
            time.sleep(2 * (i + 1))
            continue

        return data

    raise Exception("API request failed")

def login():
    data = safe_get({
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    })

    token = data["query"]["tokens"]["logintoken"]

    r = session.post(API, data={
        "action": "login",
        "lgname": USERNAME,
        "lgpassword": PASSWORD,
        "lgtoken": token,
        "format": "json"
    })

    result = r.json().get("login", {}).get("result")
    if result != "Success":
        raise Exception(f"Login failed: {r.text[:200]}")

def get_watchlist():
    r = safe_get({
        "action": "query",
        "list": "watchlistraw",
        "wrlimit": "max",
        "format": "json"
    })

    if "query" in r and "watchlistraw" in r["query"]:
        return [p["title"] for p in r["query"]["watchlistraw"]]

    if "watchlistraw" in r:
        return [p["title"] for p in r["watchlistraw"]]

    return []

def get_page(title):
    r = safe_get({
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "titles": title,
        "format": "json"
    })

    pages = r["query"]["pages"]
    return next(iter(pages.values()))["revisions"][0]["*"]


def get_csrf():
    r = safe_get({
        "action": "query",
        "meta": "tokens",
        "format": "json"
    })
    return r["query"]["tokens"]["csrftoken"]


def edit_page(title, text, summary):
    token = get_csrf()

    r = session.post(API, data={
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "format": "json"
    })

    print("Edit:", title, r.text[:200])

def parse_ago(value):
    m = re.match(r"^\s*(\d+)\s*([mdhw])\s*$", value.lower())
    if not m:
        return 999999  # fallback

    n = int(m.group(1))
    unit = m.group(2)

    return n * {"m":1/60,"h":1,"d":24,"w":168}[unit]


def get_config(text):
    code = mwparserfromhell.parse(text)

    for t in code.filter_templates():
        if t.name.matches("Autoarchive"):
            archive = str(t.get("archive").value).strip()
            ago = str(t.get("ago").value).strip()
            return archive, parse_ago(ago)

    return None, None


def resolve(pattern, title):
    now = datetime.datetime.utcnow()
    return (
        pattern
        .replace("%(fullpage)", title)
        .replace("%(year)", str(now.year))
    )


def extract_archive_blocks(text):
    pattern = re.compile(
        r'(<div class="boilerplate metadata discussion-archived".*?</div>)',
        re.S | re.I
    )
    return pattern.findall(text)


def is_old_enough(block, hours):
    # simple timestamp heuristic
    ts = re.findall(r"\d{2}:\d{2}, \d{1,2} \w+ \d{4}", block)

    if not ts:
        return False

    try:
        last = datetime.datetime.strptime(ts[-1], "%H:%M, %d %B %Y")
        age = (datetime.datetime.utcnow() - last).total_seconds() / 3600
        return age >= hours
    except:
        return False


def process(title):
    text = get_page(title)

    pattern, hours = get_config(text)
    if not pattern:
        return

    archive_title = resolve(pattern, title)

    blocks = extract_archive_blocks(text)

    if not blocks:
        return

    keep = text
    to_archive = []

    for b in blocks:
        if is_old_enough(b, hours):
            to_archive.append(b)
            keep = keep.replace(b, "")

    if not to_archive:
        return

    try:
        archive_text = get_page(archive_title)
    except:
        archive_text = ""

    archive_text += "\n\n" + "\n\n".join(to_archive)

    edit_page(archive_title, archive_text, "Bot: archiving discussions")
    edit_page(title, keep, "Bot: removing archived sections")

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
