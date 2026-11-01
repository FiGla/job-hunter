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
        jtype=None, salary=None, snippet=""):
    return {
        "source": source, "title": clean(title, 160),
        "company": clean(company, 120) or "Unknown",
        "location": clean(location, 120) or "Switzerland",
        "url": url, "posted": iso(posted), "remote": bool(remote),
        "type": jtype, "salary": salary, "snippet": clean(snippet),
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
                       sal, j.get("jobExcerpt")))
    return out


def adzuna():
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("set ADZUNA_APP_ID and ADZUNA_APP_KEY")
    out = []
    for page in range(1, 11):
        r = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/ch/search/{page}",
            params={"app_id": app_id, "app_key": app_key, "results_per_page": 50,
                    "sort_by": "date", "content-type": "application/json"},
            headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        res = r.json().get("results", [])
        for j in res:
            sal = None
            if j.get("salary_min") and j.get("salary_max"):
                sal = f'CHF {int(j["salary_min"]):,}–{int(j["salary_max"]):,}'
            out.append(job("Adzuna", j["title"], (j.get("company") or {}).get("display_name"),
                           (j.get("location") or {}).get("display_name"), j["redirect_url"],
                           j.get("created"), False,
                           (j.get("contract_time") or "").replace("_", " ") or None,
                           sal, j.get("description")))
        if len(res) < 50:
            break
        time.sleep(0.5)
    return out


def jooble():
    key = os.getenv("JOOBLE_API_KEY")
    if not key:
        raise SkipSource("set JOOBLE_API_KEY")
    out = []
    for page in range(1, 6):
        r = requests.post(f"https://jooble.org/api/{key}",
                          json={"keywords": "", "location": "Switzerland", "page": page},
                          headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        res = r.json().get("jobs", [])
        if not res:
            break
        for j in res:
            out.append(job("Jooble", j["title"], j.get("company"), j.get("location"),
                           j["link"], j.get("updated"), False, j.get("type") or None,
                           j.get("salary") or None, j.get("snippet")))
    return out


# To add a site: write a function returning job(...) dicts and register it here.
SOURCES = {"Arbeitnow": arbeitnow, "Remotive": remotive, "Jobicy": jobicy,
           "Adzuna": adzuna, "Jooble": jooble}


def main():
    jobs, status = [], {}
    for name, fn in SOURCES.items():
        try:
            found = fn()
            jobs += found
            status[name] = {"ok": True, "count": len(found)}
        except SkipSource as e:
            status[name] = {"ok": False, "count": 0, "note": f"skipped: {e}"}
        except Exception as e:  # one broken source must not break the build
            status[name] = {"ok": False, "count": 0, "note": f"{type(e).__name__}: {e}"[:200]}
        print(name, status[name], file=sys.stderr)

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
    if not unique:
        sys.exit("No jobs collected from any source")


if __name__ == "__main__":
    main()
