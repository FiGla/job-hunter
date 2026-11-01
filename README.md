# Swiss Jobs Board

Aggregates **software engineering** jobs in Switzerland (high-mid to lead level, relocation support mentioned) from several public job APIs into one searchable page, hosted free on GitHub Pages and refreshed every 6 hours by GitHub Actions.

## Setup (about 3 minutes)
1. Create a GitHub repo and push these files to the `main` branch.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → "Update jobs and deploy site" → Run workflow**. Your site appears at `https://<user>.github.io/<repo>/`.

## Sources
| Source | Key needed | Notes |
|---|---|---|
| Arbeitnow | no | Filtered to Swiss locations |
| Remotive | no | Remote jobs open to Switzerland |
| Jobicy | no | Remote jobs, `geo=switzerland` |
| Adzuna | free | Largest Swiss coverage. Get keys at developer.adzuna.com |
| Jooble | free | Get a key at jooble.org/api/about |

Add keys under **Settings → Secrets and variables → Actions**: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`. Sources without keys are skipped.

## Run locally
    pip install requests
    python scraper/fetch_jobs.py
    python -m http.server -d site 8000   # open http://localhost:8000

## Add a source
Write a function in `scraper/fetch_jobs.py` that returns a list of `job(...)` dicts and add it to `SOURCES`.

## What gets kept
- **Role**: title must be an engineering role in software, backend, frontend, full-stack, mobile, DevOps/SRE, platform/cloud, embedded, ML/AI or data engineering. Sales, support, hardware, mechanical and similar roles are dropped. Edit `ROLE`, `TECH` and `NOT_SWE` in the script to change this.
- **Level**: Senior, Lead/Staff/Principal/Architect, or untitled roles asking for 4+ years of experience ("high mid"). Junior, intern and unclear-level roles are dropped.
- **Relocation**: the posting must mention relocation help (English, German or French). "No relocation", "willing to relocate" and similar are ignored. Set the env var `REQUIRE_RELOCATION=0` to see matching roles without this requirement.
- Adzuna and Jooble only return short previews, so they search for the word "relocation" on their side and those jobs are shown as "Relocation (unconfirmed)".
