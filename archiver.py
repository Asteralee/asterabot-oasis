import requests
import re
import datetime
import mwparserfromhell
import time

API = "https://test.wikipedia.org/w/api.php"

S = requests.Session()

def login(username, password):
    token = S.get(API, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }).json()["query"]["tokens"]["logintoken"]

    S.post(API, data={
        "action": "login",
        "lgname": username,
        "lgpassword": password,
        "lgtoken": token,
        "format": "json"
    })


def get_watchlist():
    r = S.get(API, params={
        "action": "query",
        "list": "watchlistraw",
        "wrlimit": "max",
        "format": "json"
    }).json()

    return [p["title"] for p in r.get("query", {}).get("watchlistraw", [])]


def get_page(title):
    r = S.get(API, params={
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "titles": title,
        "format": "json"
    }).json()

    pages = r["query"]["pages"]
    return next(iter(pages.values()))["revisions"][0]["*"]


def edit_page(title, text, summary):
    token = S.get(API, params={
        "action": "query",
        "meta": "tokens",
        "format": "json"
    }).json()["query"]["tokens"]["csrftoken"]

    S.post(API, data={
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "format": "json"
    })


def parse_ago(value):
    m = re.match(r"(\d+)([hdmw])", value.lower())
    n, u = int(m.group(1)), m.group(2)
    return n * {"m":1/60,"h":1,"d":24,"w":168}[u]


def resolve(pattern, title):
    now = datetime.datetime.utcnow()
    return (pattern
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
    sections = [(parts[i], parts[i+1] if i+1 < len(parts) else "") for i in range(1, len(parts), 2)]
    return lead, sections


def has_marker(text):
    return re.search(r'^\s*<div[^>]*discussion-archived', text, re.I)


def latest_ts(text):
    matches = re.findall(r"\d{2}:\d{2}, \d{1,2} \w+ \d{4}", text)
    out = []
    for m in matches:
        try:
            out.append(datetime.datetime.strptime(m, "%H:%M, %d %B %Y"))
        except:
            pass
    return max(out).replace(tzinfo=datetime.timezone.utc) if out else None


def old_enough(text, hours):
    ts = latest_ts(text)
    if not ts:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - ts).total_seconds()/3600 >= hours


def process(title):
    text = get_page(title)
    pattern, hours = get_config(text)
    if not pattern:
        return

    archive_title = resolve(pattern, title)
    lead, sections = split_sections(text)

    keep, move = [], []

    for h, b in sections:
        s = h + b
        if has_marker(s) and old_enough(s, hours):
            move.append(s)
        else:
            keep.append(s)

    if not move:
        return

    new_text = lead + "".join(keep)

    try:
        archive_text = get_page(archive_title)
    except:
        archive_text = ""

    archive_text += "\n\n" + "\n\n".join(move)

    edit_page(archive_title, archive_text, "Bot: archiving")
    edit_page(title, new_text, "Bot: removing archived sections")


def run():
    for title in get_watchlist():
        try:
            print("Processing:", title)
            process(title)
            time.sleep(5)
        except Exception as e:
            print("Error:", e)


if __name__ == "__main__":
    login("USERNAME", "PASSWORD")
    run()
