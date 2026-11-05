"""Scrape every Bellhaven community from the website.

Coverage rules (learned the hard way):
- /communities is paginated -> walk every page.
- The homepage links communities that are NOT in the directory (e.g. a 'new this year' banner) -> crawl it too.
- Street / zip / phone / administrator only exist on the detail page -> visit every detail page.
- Dedupe by slug.
"""
import json
import re
import sys
import requests
from bs4 import BeautifulSoup
import config

LABELS = {"address", "phone", "care offerings", "care offering", "administrator", "care"}
CITY_RE = re.compile(r"^(.+?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?$")
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")


def _get(path):
    r = requests.get(f"{config.BASE_URL}{path}", timeout=30)
    r.raise_for_status()
    return r.text


def _community_links(html):
    soup = BeautifulSoup(html, "html.parser")
    slugs = set()
    for a in soup.find_all("a", href=True):
        m = re.match(r"^(?:https?://[^/]+)?/communities/([\w-]+)/?$", a["href"])
        if m:
            slugs.add(m.group(1))
    return slugs


def discover_slugs():
    slugs = set()
    # homepage (may advertise communities missing from the directory)
    home = _get("/")
    slugs |= _community_links(home)
    claimed = re.search(r"(\d+)\s+communities", home)
    claimed = int(claimed.group(1)) if claimed else None

    page = 1
    while True:
        html = _get(f"/communities?page={page}")
        found = _community_links(html)
        slugs |= found
        soup = BeautifulSoup(html, "html.parser")
        has_next = any("next" in a.get_text(strip=True).lower() for a in soup.find_all("a", href=True))
        if not found or not has_next:
            break
        page += 1
    return sorted(slugs), claimed


def _lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup, [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]


def parse_detail(slug, html):
    soup, lines = _lines(html)
    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else lines[0]

    rec = {"slug": slug, "name": name, "street": "", "city": "", "state": "", "zip": "",
           "phone": "", "care_offerings": [], "administrator": "",
           "url": f"{config.BASE_URL}/communities/{slug}"}

    # phone: first phone-looking string on the page (phone is evidence only, never a match key)
    for l in lines:
        m = PHONE_RE.search(l)
        if m:
            rec["phone"] = m.group(0)
            break

    # city/state/zip line, street = line before it
    for i, l in enumerate(lines):
        m = CITY_RE.match(l)
        if m:
            rec["city"], rec["state"], rec["zip"] = m.group(1).strip(), m.group(2), m.group(3)
            prev = lines[i - 1] if i > 0 else ""
            if prev.lower().rstrip(":") not in LABELS:
                rec["street"] = prev
            break

    # label-driven fields
    def after_label(label_words):
        for i, l in enumerate(lines):
            low = l.lower().rstrip(":")
            for lw in label_words:
                if low == lw:
                    return i + 1, None
                if low.startswith(lw + ":"):
                    return i + 1, l.split(":", 1)[1].strip()
        return None, None

    i, inline = after_label(["administrator"])
    rec["administrator"] = inline if inline else (lines[i] if i is not None and i < len(lines) else "")

    i, inline = after_label(["care offerings", "care offering", "care"])
    offers = []
    if inline:
        offers = [inline]
    elif i is not None:
        while i < len(lines):
            low = lines[i].lower().rstrip(":")
            if low in LABELS or low.startswith("←") or low.startswith("corporate") or low.startswith("©"):
                break
            if CITY_RE.match(lines[i]) or PHONE_RE.search(lines[i]):
                break
            offers.append(lines[i]); i += 1
    # split concatenated offerings like "Assisted LivingMemory Support" or comma lists
    split = []
    for o in offers:
        o = re.sub(r"(?<=[a-z])(?=[A-Z])", ", ", o)
        split.extend([p.strip() for p in re.split(r",|/|\n", o) if p.strip()])
    rec["care_offerings"] = sorted(set(split))
    return rec


def scrape():
    slugs, claimed = discover_slugs()
    records = []
    for s in slugs:
        try:
            records.append(parse_detail(s, _get(f"/communities/{s}")))
        except Exception as e:  # keep going; report at end
            print(f"[warn] failed {s}: {e}", file=sys.stderr)
    if claimed and claimed != len(records):
        print(f"[warn] homepage claims {claimed} communities, scraped {len(records)}", file=sys.stderr)
    missing = [r["slug"] for r in records if not r["street"] or not r["zip"]]
    if missing:
        print(f"[warn] missing street/zip for: {missing}", file=sys.stderr)
    return records


if __name__ == "__main__":
    recs = scrape()
    with open(config.WEBSITE_JSON, "w") as f:
        json.dump(recs, f, indent=2)
    print(f"scraped {len(recs)} communities -> {config.WEBSITE_JSON}")
    for r in recs[:3]:
        print(json.dumps(r, indent=2))
