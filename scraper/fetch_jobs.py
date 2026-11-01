#!/usr/bin/env python3
"""Collect Swiss job posts from several public job APIs into site/jobs.json."""
import hashlib, html, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "site" / "jobs.json"
UA = {"User-Agent": "swiss-jobs-aggregator/1.0 (GitHub Pages project)"}
TIMEOUT = 30

SWISS = re.compile(
    r"switzerland|schweiz|suisse|svizzera|\bch\b|z[uü]rich|gen[eè]v|geneva|basel|bern|"
    r"lausanne|luzern|lucerne|\bzug\b|winterthur|st\.? ?gallen|lugano|biel|fribourg|"
    r"neuch[aâ]tel|schaffhausen|\bchur\b|aargau|ticino|vaud|valais|thurgau",
    re.I,
)


class SkipSource(Exception):
    pass


# ---------------- what to keep (edit these to taste) ----------------
# Relocation is required by default. Set REQUIRE_RELOCATION=0 to keep every matching role.
REQUIRE_RELOCATION = os.getenv("REQUIRE_RELOCATION", "1") != "0"

ROLE = re.compile(r"engineer|developer|entwickl|ingenieur|architect|programmer|\bsre\b|\bswe\b", re.I)
TECH = re.compile(
    r"software|back-?end|back end|front-?end|front end|full[- ]?stack|devops|\bsre\b|site reliability|"
    r"platform|cloud|infrastructure|mobile|\bios\b|android|embedded|firmware|machine learning|\bml\b|"
    r"\bai\b|data engineer|security engineer|java\b|python|golang|\bgo\b|rust|c\+\+|\.net|typescript|"
    r"react|kotlin|scala|swe\b", re.I)
NOT_SWE = re.compile(
    r"sales|pre-?sales|business|account|customer|support engineer|technical support|solutions?\s+(engineer|architect)|"
    r"mechanical|electrical|civil|chemical|process|manufacturing|hardware|structural|construction|field|"
    r"biomedical|quality engineer|maintenance|facility|recruit", re.I)
JUNIOR = re.compile(
    r"\b(junior|jr|intern|internship|trainee|graduate|apprentice|working student|werkstudent|praktikum|"
    r"praktikant\w*|lehrling|stage|entry[- ]level|berufseinsteiger\w*)\b", re.I)
LEAD = re.compile(r"\b(lead|staff|principal|head of|architect|distinguished)\b", re.I)
SENIOR = re.compile(r"\b(senior|sr|expert|iii|iv|erfahren\w*)\b", re.I)
YEARS = [
    re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?(?:years?|yrs?|jahre\w*|ans)\b[^.]{0,50}?"
               r"(?:experience|erfahrung|exp[eé]rience)", re.I),
    re.compile(r"(?:experience|erfahrung|exp[eé]rience)[^.]{0,40}?(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?"
               r"(?:years?|yrs?|jahre\w*|ans)\b", re.I),
]
RELO_HIT = re.compile(
    r"relocation|umzug\w*|d[eé]m[eé]nagement|(?:help|assist|support)\w*\s+(?:you\s+|with\s+)?(?:to\s+)?relocat\w+", re.I)
SUPPORT = re.compile(
    r"support|assist|package|bonus|allowance|budget|benefit|help|offer|provid|cover|reimburs|stipend|paid|lump|"
    r"sponsor|included|available|possible|unterst|hilfe|kosten|zuschuss|pauschale|angebot|[uü]bernehm|"
    r"aide|prise en charge|soutien|financ", re.I)
NEGATION = re.compile(r"\b(no|not|without|cannot|unable|unfortunately|keine?|kein|ohne|nicht|sans|pas de)\b|n't", re.I)
CANDIDATE_SIDE = re.compile(r"(open|willing|able|ready|prepared|bereit)\s+(to|for|zu|zum)\s+$", re.I)


def is_swe(title):
    return bool(ROLE.search(title) and TECH.search(title) and not NOT_SWE.search(title))


def seniority(title, text):
    """'lead' | 'senior' | 'mid' (high-mid: >=4 years asked) | None (junior or unclear)."""
    if JUNIOR.search(title):
        return None
    if LEAD.search(title):
        return "lead"
    if SENIOR.search(title):
        return "senior"
    years = 0
    for pat in YEARS:
        for m in pat.finditer(text):
            years = max(years, int(m.group(2) or m.group(1)))
    return "mid" if 4 <= years <= 15 else None


def has_relocation(text):
    for m in RELO_HIT.finditer(text):
        before, after = text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 40]
        if NEGATION.search(before[-25:]) or re.match(r"\s*(is\s+|are\s+)?(not|n't|unfortunately)", after, re.I):
            continue
        if CANDIDATE_SIDE.search(before):
            continue
        if m.group(0).lower().startswith(("help", "assist", "support")):
            return True
        if SUPPORT.search(text[max(0, m.start() - 80):m.end() + 80]):
            return True
    return False


def clean(text, n=240):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[: n - 1] + "…" if len(text) > n else text


def iso(value):
    """Normalise unix seconds / ISO strings to ISO UTC."""
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return None


def job(source, title, company, location, url, posted=None, remote=False,
        jtype=None, salary=None, snippet="", relo_hint=False):
    plain = clean(snippet, 10**6)
    return {
        "source": source, "title": clean(title, 160),
        "company": clean(company, 120) or "Unknown",
        "location": clean(location, 120) or "Switzerland",
        "url": url, "posted": iso(posted), "remote": bool(remote),
        "type": jtype, "salary": salary, "snippet": clean(snippet),
        "software": is_swe(title), "level": seniority(title, plain),
        "relocation": "yes" if has_relocation(plain) else ("likely" if relo_hint else None),
    }


# ---------------- sources (each returns a list of job(...)) ----------------
def arbeitnow():
    url, out = "https://www.arbeitnow.com/api/job-board-api", []
    for _ in range(8):
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for j in data.get("data", []):
            if SWISS.search(j.get("location", "")):
                out.append(job("Arbeitnow", j["title"], j["company_name"], j["location"],
                               j["url"], j.get("created_at"), j.get("remote"),
                               ", ".join(j.get("job_types") or []) or None,
                               snippet=j.get("description")))
        url = (data.get("links") or {}).get("next")
        if not url:
            break
    return out


def remotive():
    r = requests.get("https://remotive.com/api/remote-jobs", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [
        job("Remotive", j["title"], j["company_name"], j.get("candidate_required_location"),
            j["url"], j.get("publication_date"), True,
            (j.get("job_type") or "").replace("_", " ") or None,
            j.get("salary") or None, j.get("description"))
        for j in r.json().get("jobs", [])
        if SWISS.search(j.get("candidate_required_location", ""))
    ]


def jobicy():
    r = requests.get("https://jobicy.com/api/v2/remote-jobs",
                     params={"count": 100, "geo": "switzerland"},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        sal = None
        if j.get("salaryMin"):
            sal = f'{j["salaryMin"]}–{j.get("salaryMax", "")} {j.get("salaryCurrency", "")}'.strip()
        out.append(job("Jobicy", j["jobTitle"], j["companyName"], j.get("jobGeo"), j["url"],
                       j.get("pubDate"), True, ", ".join(j.get("jobType") or []) or None,
                       sal, j.get("jobDescription") or j.get("jobExcerpt")))
    return out


QUERIES = ["software engineer relocation", "senior software developer relocation",
           "backend engineer relocation", "devops engineer relocation",
           "machine learning engineer relocation"]


def adzuna():
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("set ADZUNA_APP_ID and ADZUNA_APP_KEY")
    out = []
    for q in QUERIES:
        for page in range(1, 4):
            r = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/ch/search/{page}",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": 50,
                        "what": q, "sort_by": "date", "content-type": "application/json"},
                headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            res = r.json().get("results", [])
            for j in res:
                sal = None
                if j.get("salary_min") and j.get("salary_max"):
                    sal = f'CHF {int(j["salary_min"]):,}-{int(j["salary_max"]):,}'
                out.append(job("Adzuna", j["title"], (j.get("company") or {}).get("display_name"),
                               (j.get("location") or {}).get("display_name"), j["redirect_url"],
                               j.get("created"), False,
                               (j.get("contract_time") or "").replace("_", " ") or None,
                               sal, j.get("description"), relo_hint=True))
            if len(res) < 50:
                break
            time.sleep(0.5)
    return out


def jooble():
    key = os.getenv("JOOBLE_API_KEY")
    if not key:
        raise SkipSource("set JOOBLE_API_KEY")
    out = []
    for q in QUERIES:
        for page in range(1, 3):
            r = requests.post(f"https://jooble.org/api/{key}",
                              json={"keywords": q, "location": "Switzerland", "page": page},
                              headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            res = r.json().get("jobs", [])
            if not res:
                break
            for j in res:
                out.append(job("Jooble", j["title"], j.get("company"), j.get("location"),
                               j["link"], j.get("updated"), False, j.get("type") or None,
                               j.get("salary") or None, j.get("snippet"), relo_hint=True))
            time.sleep(0.5)
    return out


# To add a site: write a function returning job(...) dicts and register it here.
SOURCES = {"Arbeitnow": arbeitnow, "Remotive": remotive, "Jobicy": jobicy,
           "Adzuna": adzuna, "Jooble": jooble}


def main():
    jobs, status = [], {}
    for name, fn in SOURCES.items():
        try:
            found = fn()
            kept = [j for j in found if j["software"] and j["level"]
                    and (j["relocation"] or not REQUIRE_RELOCATION)]
            jobs += kept
            status[name] = {"ok": True, "count": len(kept), "seen": len(found)}
        except SkipSource as e:
            status[name] = {"ok": False, "count": 0, "note": f"skipped: {e}"}
        except Exception as e:  # one broken source must not break the build
            status[name] = {"ok": False, "count": 0, "note": f"{type(e).__name__}: {e}"[:200]}
        print(name, status[name], file=sys.stderr)

    jobs.sort(key=lambda j: j["relocation"] != "yes")  # confirmed relocation wins on duplicates
    seen, unique = set(), []
    for j in jobs:
        key = re.sub(r"\W+", "", f'{j["title"]}{j["company"]}{j["location"]}'.lower())
        if key in seen or not j["url"]:
            continue
        seen.add(key)
        j["id"] = hashlib.md5(j["url"].encode()).hexdigest()[:12]
        unique.append(j)
    unique.sort(key=lambda j: j["posted"] or "", reverse=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": status, "jobs": unique,
    }, ensure_ascii=False))
    print(f"Wrote {len(unique)} jobs to {OUT}", file=sys.stderr)
    if not any(s["ok"] for s in status.values()):
        sys.exit("Every source failed")


if __name__ == "__main__":
    main()
