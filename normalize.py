"""Normalisation helpers. Address is the primary key for 'same facility'; name is only evidence."""
import re
try:
    from rapidfuzz import fuzz
except ImportError:  # fallback so the pipeline still runs without rapidfuzz
    import difflib

    class fuzz:  # noqa: N801
        @staticmethod
        def ratio(a, b):
            return difflib.SequenceMatcher(None, a, b).ratio() * 100

        @staticmethod
        def token_set_ratio(a, b):
            ta, tb = set(a.split()), set(b.split())
            inter = " ".join(sorted(ta & tb))
            s1, s2 = " ".join(sorted(ta)), " ".join(sorted(tb))
            return max(fuzz.ratio(inter, s1), fuzz.ratio(inter, s2), fuzz.ratio(s1, s2)) if inter else fuzz.ratio(s1, s2)

_STREET_ABBR = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "lane": "ln",
    "boulevard": "blvd", "court": "ct", "place": "pl", "circle": "cir", "parkway": "pkwy",
    "highway": "hwy", "pike": "pike", "pk": "pike", "terrace": "ter", "trail": "trl", "way": "way",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
    "saint": "st", "mount": "mt", "fort": "ft",
}

_NAME_SYNONYMS = {
    "&": "and", "centre": "center", "rehab": "rehabilitation",
    "healthcare": "health care",
}
_NAME_STOP = {"the", "of", "at", "a", "an", "-", "–"}


def norm_street(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[.,#]", " ", s)
    s = re.sub(r"\b(suite|ste|unit|apt)\b.*$", "", s)      # drop suite numbers
    toks = [_STREET_ABBR.get(t, t) for t in s.split()]
    return " ".join(toks).strip()


def zip5(z) -> str:
    m = re.search(r"\d{5}", str(z or ""))
    return m.group(0) if m else ""


def addr_key(street, zipcode) -> str:
    return f"{norm_street(street)}|{zip5(zipcode)}"


def norm_name(n: str) -> str:
    n = (n or "").lower()
    n = n.replace("(parent account)", "")
    for k, v in _NAME_SYNONYMS.items():
        n = n.replace(k, v)
    n = re.sub(r"[^\w\s]", " ", n)
    toks = [t for t in n.split() if t not in _NAME_STOP]
    return " ".join(toks)


def name_similarity(a: str, b: str) -> int:
    return int(fuzz.token_set_ratio(norm_name(a), norm_name(b)))


def names_same(a: str, b: str, threshold: int) -> bool:
    return norm_name(a) == norm_name(b) or fuzz.ratio(norm_name(a), norm_name(b)) >= threshold
