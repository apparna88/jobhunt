# jobhunt

Find **fresh, real** job postings straight from company ATS boards (Greenhouse,
Lever, Ashby, Workday) — not stale LinkedIn reposts or ghost jobs.

Jobs land on a company's own ATS *before* they hit aggregators, and those
timestamps can't be gamed — so `jobhunt` shows you what's genuinely new, filtered
to exactly what you can apply to.

- **Zero dependencies.** Pure Python 3.9+ standard library.
- **Real freshness.** Uses each posting's true publish date from the source ATS.
- **Filters that matter:** age, title, seniority, tech stack, salary, visa language,
  and per-city work-mode rules (e.g. "remote must be US, NYC only hybrid, CT any").
- **241+ direct employers** included, all API-validated. Easy to add more.

## Quick start

```bash
git clone https://github.com/apparna88/jobhunt.git
cd jobhunt
python3 jobhunt.py          # runs with the default profile.json
```

Results print to the terminal and (if `html` is set in your profile) write `hits.html`.

**Make it yours:** edit `profile.json` directly, or — to keep your edits private and
avoid git conflicts — copy it to `profile.local.json` (git-ignored, and used
automatically when present):

```bash
cp profile.json profile.local.json   # then edit profile.local.json
```

## Configure your search

Edit `profile.json`. Every field is optional; any CLI flag overrides it.

| Field | Meaning |
|-------|---------|
| `title` | keep if the title contains **any** of these |
| `exclude` | drop if the title contains any (e.g. intern, junior) |
| `level` | keep only if the title contains any (e.g. senior, staff) — omit to include all levels |
| `stack` | keep if the description/title contains **any** of these (whole-word: `java` ≠ `javascript`) |
| `max_age` | max posting age in days |
| `min_salary` | minimum parsed salary |
| `locations` | per-city work-mode rules (see below) |
| `html` | filename to write an HTML table to |

### Location rules

```json
"locations": {
  "remote": "us",
  "onsite_hybrid": [
    {"cities": ["new york", "nyc"], "modes": ["hybrid"]},
    {"cities": ["connecticut", "ct", "stamford"], "modes": ["onsite", "hybrid", "remote"]}
  ]
}
```

- `remote`: `"us"` (US-only remote), `"any"`, or `"none"`.
- Each `onsite_hybrid` zone: match a city → allow only the listed modes.
  A remote role restricted to states you're not in is dropped automatically.

## CLI flags (override the profile per-run)

```bash
python3 jobhunt.py --max-age 4 --level "" --stack "react,typescript" --csv out.csv
```

`--title --stack --exclude --level --mode --city --min-salary --max-age
--us-remote/--no-us-remote --sponsor-only --include-excluded --json --csv --html`

## Add companies

Edit `companies.json`. Each entry is a direct company ATS board:

```json
{"name": "Stripe",  "type": "greenhouse", "token": "stripe"}
{"name": "Notion",  "type": "ashby",      "token": "notion"}
{"name": "Spotify", "type": "lever",      "token": "spotify"}
{"name": "NVIDIA",  "type": "workday",    "tenant": "nvidia", "host": "wd5", "site": "NVIDIAExternalCareerSite"}
```

- **Greenhouse/Lever/Ashby:** `token` = the company slug in its careers URL.
- **Workday:** grab the company's real `*.myworkdayjobs.com` URL and run
  `python3 wd_add.py "<url>"` — it parses, validates, and appends it.

## How it works

For each company, `jobhunt` calls that ATS's public JSON board, normalizes every
posting (title, location, publish date, description, salary, work mode), then
applies your filters. It's read-only and hits only public endpoints.

## License

MIT
