#!/usr/bin/env python3
"""
jobhunt.py - Find fresh, real job postings straight from company ATS boards
(Greenhouse + Lever), not LinkedIn reposts.

Filters: age, title keywords, visa language, work mode + cities, salary, tech stack.
Stdlib only. Python 3.9+.

Examples:
  python3 jobhunt.py --title "software engineer,backend" --max-age 2 \
      --mode remote,hybrid --city "new york,austin" \
      --stack python,go --min-salary 150000

  python3 jobhunt.py --title "data engineer" --sponsor-only --html out.html
"""
import argparse, concurrent.futures as cf, csv, html, json, os, re, sys
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

UA = {"User-Agent": "jobhunt/1.0 (personal job search)"}
HERE = os.path.dirname(os.path.abspath(__file__))

# --- visa language patterns ---------------------------------------------------
# NEGATIVE = posting rules out sponsorship / non-citizens -> excluded by default.
NEG_VISA = [
    r"\bno\b[^.]{0,30}\bsponsor",
    r"not\b[^.]{0,20}\b(?:able|available)\b[^.]{0,20}sponsor",
    r"unable to sponsor",
    r"without\b[^.]{0,20}sponsor",
    r"do(?:es)? not\b[^.]{0,20}sponsor",
    r"sponsorship is not",
    r"no visa",
    r"u\.?s\.? citizen",
    r"us citizenship",
    r"citizenship (?:is )?required",
    r"green ?card (?:holder)?s? only",
    r"gc/?usc",
    r"usc/?gc",
    r"must be (?:a )?(?:us|u\.s\.) (?:citizen|person)",
    r"security clearance",
    r"authorized to work[^.]{0,40}without (?:visa )?sponsorship",
    r"legally authorized[^.]{0,60}without (?:visa )?sponsorship",
]
# POSITIVE = posting explicitly offers sponsorship.
POS_VISA = [
    r"visa sponsorship (?:is )?available",
    r"will sponsor",
    r"we sponsor",
    r"offer(?:s)? (?:visa )?sponsorship",
    r"sponsorship (?:is )?(?:offered|available|provided)",
    r"h-?1b",
    r"open to sponsor",
    r"happy to sponsor",
]
NEG_RE = re.compile("|".join(NEG_VISA), re.I)
POS_RE = re.compile("|".join(POS_VISA), re.I)

_AMT = r"\d{2,3}(?:,\d{3})|\d{2,3}(?:\.\d+)?\s?[kK]"
SAL_RE = re.compile(rf"\$\s?({_AMT})(?:\s?[-–to]{{1,3}}\s?\$?\s?({_AMT}))?")

def _num(s):
    s = s.replace(",", "").strip().lower()
    if s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    n = int(re.sub(r"\D", "", s))
    return n * 1000 if n < 1000 else n

def parse_salary(text):
    """Return (min,max) best-guess annual salary found in text, or (None,None)."""
    best = (None, None)
    for m in SAL_RE.finditer(text):
        lo = _num(m.group(1))
        hi = _num(m.group(2)) if m.group(2) else lo
        if lo < 30000:  # skip hourly/small numbers
            continue
        if best[0] is None or hi > (best[1] or 0):
            best = (lo, hi)
    return best

def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def fetch(url, data=None):
    hdr = dict(UA)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdr.update({"Content-Type": "application/json", "Accept": "application/json"})
    req = urllib.request.Request(url, data=body, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        e.close()  # drain error body so Py3.14 GC doesn't warn
        raise RuntimeError(f"HTTP {e.code}") from None

_REL_RE = re.compile(r"(\d+)\s*\+?\s*day", re.I)
def rel_age_days(posted_on):
    """Parse Workday 'Posted 3 Days Ago' / 'Today' / 'Yesterday' -> days."""
    s = (posted_on or "").lower()
    if "today" in s:
        return 0
    if "yesterday" in s:
        return 1
    m = _REL_RE.search(s)
    if m:
        return int(m.group(1)) + (1 if "+" in s else 0)
    return None

# --- ATS adapters -------------------------------------------------------------
def from_greenhouse(co, a=None):
    url = f"https://boards-api.greenhouse.io/v1/boards/{co['token']}/jobs?content=true"
    out = []
    for j in fetch(url).get("jobs", []):
        posted = j.get("first_published") or j.get("updated_at")
        loc = (j.get("location") or {}).get("name", "") or ""
        body = strip_html(j.get("content", ""))
        out.append(dict(
            company=co["name"], title=j.get("title", ""), location=loc,
            posted=posted, url=j.get("absolute_url", ""),
            text=f"{j.get('title','')} {loc} {body}", workplace=None))
    return out

def from_lever(co, a=None):
    url = f"https://api.lever.co/v0/postings/{co['token']}?mode=json"
    out = []
    for j in fetch(url):
        cats = j.get("categories") or {}
        loc = cats.get("location", "") or ""
        ts = j.get("createdAt")
        posted = datetime.fromtimestamp(ts/1000, timezone.utc).isoformat() if ts else None
        body = " ".join(filter(None, [
            j.get("descriptionPlain", ""), j.get("additionalPlain", ""),
            " ".join(li.get("text", "") + " " + strip_html(li.get("content", ""))
                     for li in j.get("lists", []))]))
        out.append(dict(
            company=co["name"], title=j.get("text", ""), location=loc,
            posted=posted, url=j.get("hostedUrl", ""),
            text=f"{j.get('text','')} {loc} {body}",
            workplace=(j.get("workplaceType") or "").lower() or None))
    return out

def from_ashby(co, a=None):
    url = (f"https://api.ashbyhq.com/posting-api/job-board/"
           f"{co['token']}?includeCompensation=true")
    out = []
    for j in fetch(url).get("jobs", []):
        secs = [s.get("location", "") for s in (j.get("secondaryLocations") or [])]
        loc = ", ".join(filter(None, [j.get("location", "")] + secs))
        comp = (j.get("compensation") or {}).get("compensationTierSummary", "") or \
               (j.get("compensation") or {}).get("scrapeableCompensationSalarySummary", "")
        body = f"{comp} {j.get('descriptionPlain','')}"
        out.append(dict(
            company=co["name"], title=j.get("title", ""), location=loc,
            posted=j.get("publishedAt"), url=j.get("jobUrl", ""),
            text=f"{j.get('title','')} {loc} {body}",
            workplace="remote" if j.get("isRemote") else None))
    return out

def from_workday(co, a=None):
    """Workday: POST list (cheap) -> pre-filter age/title -> GET detail per survivor.
    Company needs tenant, host (wd1/wd5/...), site."""
    base = (f"https://{co['tenant']}.{co['host']}.myworkdayjobs.com"
            f"/wday/cxs/{co['tenant']}/{co['site']}")
    max_age = getattr(a, "max_age", None)
    titles = getattr(a, "title", []) or []
    survivors, offset, seen = [], 0, 0
    for _ in range(12):  # page cap: 12 * 20 = 240 postings/company
        page = fetch(f"{base}/jobs",
                     {"appliedFacets": {}, "limit": 20, "offset": offset,
                      "searchText": titles[0] if len(titles) == 1 else ""})
        posts = page.get("jobPostings", [])
        if not posts:
            break
        ages = [rel_age_days(p.get("postedOn")) for p in posts]
        for p, age in zip(posts, ages):
            if max_age is not None and (age is None or age > max_age):
                continue
            tl = p.get("title", "").lower()
            if titles and not any(k in tl for k in titles):
                continue
            survivors.append((p, age))
        seen += len(posts)
        # Workday defaults to newest-first; stop once a full page is all too old
        if max_age is not None and posts and all(
                x is not None and x > max_age for x in ages):
            break
        if seen >= page.get("total", seen):
            break
        offset += 20

    out = []
    for p, age in survivors:
        try:
            info = fetch(f"{base}{p['externalPath']}").get("jobPostingInfo", {})
        except Exception:
            info = {}
        body = strip_html(info.get("jobDescription", ""))
        sd = info.get("startDate")  # exact YYYY-MM-DD when available
        posted = f"{sd}T00:00:00+00:00" if sd else None
        loc = info.get("location") or p.get("locationsText", "") or ""
        rt = (info.get("remoteType") or "").lower()
        wp = "remote" if "remote" in rt else ("hybrid" if "hybrid" in rt else None)
        pub = f"https://{co['tenant']}.{co['host']}.myworkdayjobs.com/{co['site']}"
        job = dict(company=co["name"], title=p.get("title", ""), location=loc,
                   posted=posted, url=pub + p["externalPath"],
                   text=f"{p.get('title','')} {loc} {body}", workplace=wp)
        if posted is None and age is not None:  # fall back to relative age
            job["_rel_age"] = age
        out.append(job)
    return out

ADAPTERS = {"greenhouse": from_greenhouse, "lever": from_lever,
            "ashby": from_ashby, "workday": from_workday}

# --- filtering ----------------------------------------------------------------
def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None

REMOTE_RE = re.compile(r"\bremote\b|work from home|\bwfh\b|distributed", re.I)
HYBRID_RE = re.compile(r"\bhybrid\b", re.I)

def work_mode(job):
    if job["workplace"]:
        if "remote" in job["workplace"]:
            return "remote"
        if "hybrid" in job["workplace"]:
            return "hybrid"
        return "onsite"
    t = job["text"]
    if HYBRID_RE.search(t):
        return "hybrid"
    if REMOTE_RE.search(job["location"]) or REMOTE_RE.search(t[:400]):
        return "remote"
    return "onsite"

NONUS = ("canada", ", can", "(can", "can)", " can ", "mexico", "brazil", "argentina",
         "colombia", "united kingdom", "uk", "ireland", "england", "scotland",
         "germany", "france", "spain", "portugal", "poland", "netherlands", "sweden",
         "norway", "switzerland", "italy", "romania", "emea", "europe", "apac",
         "latam", "india", "singapore", "australia", "japan", "china", "israel",
         "dubai", "uae", "africa", "philippines", "taiwan", "korea", "hong kong",
         "vietnam",
         # major non-US cities/provinces that appear without a country name
         "toronto", "vancouver", "montreal", "ottawa", "calgary", "edmonton",
         "waterloo", "ontario", "quebec", "alberta", "british columbia",
         "london", "dublin", "berlin", "munich", "paris", "amsterdam", "barcelona",
         "madrid", "lisbon", "zurich", "warsaw", "krakow", "bucharest",
         "bangalore", "bengaluru", "hyderabad", "pune", "chennai", "gurgaon",
         "noida", "mumbai", "delhi", "tel aviv", "sydney", "melbourne", "tokyo",
         "seoul", "shanghai", "beijing", "são paulo", "sao paulo", "mexico city")
def is_us_remote(location):
    """True unless the remote location clearly names a non-US country."""
    return not any(x in location.lower() for x in NONUS)

NATIONWIDE = ("united states", "u.s.a", "usa", "nationwide", "anywhere",
              "fully remote", "across the us", "remote - us", "us remote",
              "remote, us", "(us)", "(u.s", "(usa)")
# Full state names + unambiguous abbrevs (NY/CT excluded; they're allowed regions).
_STATES = ("alabama", "alaska", "arizona", "arkansas", "california", "colorado",
           "delaware", "florida", "georgia", "idaho", "illinois", "indiana",
           "iowa", "kansas", "kentucky", "louisiana", "maryland", "massachusetts",
           "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska",
           "nevada", "new hampshire", "new jersey", "new mexico", "north carolina",
           "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
           "rhode island", "south carolina", "south dakota", "tennessee", "texas",
           "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin",
           "wyoming", "durham", "atlanta", "austin", "denver", "seattle", "miami",
           "chicago", "boston", "los angeles", "san francisco", "bay area",
           "palo alto", "mountain view", "sunnyvale", "san jose", "cupertino",
           "menlo park", "redmond", "bellevue", "portland", "dallas", "houston",
           "phoenix", "san diego", "raleigh", "nashville", "salt lake", "irvine",
           "santa clara", "santa monica", "culver city", "pittsburgh", "columbus")
_ABBR = ("ca", "tx", "fl", "ga", "nc", "sc", "va", "az", "co", "wa", "nj", "il",
         "mn", "wi", "mo", "tn", "al", "nv", "ut", "nm", "ks", "ia", "md", "dc")
_GEO_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(_STATES) + r")(?![a-z])"
    r"|(?<![a-z])(?:" + "|".join(_ABBR) + r")(?![a-z])", re.I)

def remote_region_ok(location, cities):
    """A remote role is reachable from `cities` if it's nationwide US or names an
    allowed region; drop it if it's restricted to other specific US locations."""
    l = location.lower()
    if any(c in l for c in cities):
        return True
    if any(m in l for m in NATIONWIDE):
        return True
    if _GEO_RE.search(l):
        return False  # remote but pinned to states you're not in
    return True  # bare "Remote" with no geo -> assume open

def location_ok(location, mode, rules):
    """Per-city mode rules from profile 'locations'. Example:
    {"remote":"us", "onsite_hybrid":[{"cities":["nyc"],"modes":["hybrid"]},
                                      {"cities":["ct"],"modes":["onsite","hybrid"]}]}"""
    zones = rules.get("onsite_hybrid", [])
    if mode == "remote":
        pol = rules.get("remote", "any")
        if pol == "none":
            return False
        if pol == "any":
            return True
        if not is_us_remote(location):  # pol == "us"
            return False
        allcities = [c for z in zones for c in z.get("cities", [])]
        return remote_region_ok(location, allcities)
    low = location.lower()
    for z in zones:  # onsite / hybrid must match a zone AND its allowed modes
        if any(c in low for c in z.get("cities", [])):
            return mode in z.get("modes", [])
    return False

def visa_status(text):
    if NEG_RE.search(text):
        return "EXCLUDED"
    if POS_RE.search(text):
        return "SPONSORS"
    return "silent"

def match(job, a):
    # freshness
    dt = parse_dt(job["posted"])
    if dt is not None:
        age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    else:
        age_days = job.get("_rel_age")  # Workday relative fallback
    if a.max_age is not None:
        if age_days is None or age_days > a.max_age:
            return None
    # title (any keyword), with negative + seniority filters (title only)
    tl = job["title"].lower()
    if a.title and not any(k in tl for k in a.title):
        return None
    if a.exclude and any(k in tl for k in a.exclude):
        return None
    if a.level and not any(k in tl for k in a.level):
        return None
    # tech stack: whole-word match so "java" != "javascript". Any by default.
    low = job["text"].lower()
    if a.stack:
        def has(k):
            return re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low) is not None
        hit = all(has(k) for k in a.stack) if a.stack_all else any(has(k) for k in a.stack)
        if not hit:
            return None
    # visa
    v = visa_status(job["text"])
    if a.sponsor_only and v != "SPONSORS":
        return None
    if not a.include_excluded and v == "EXCLUDED":
        return None
    # work mode + city
    mode = work_mode(job)
    loc = job["location"]
    if a.location_rules:  # per-city mode rules from profile 'locations'
        if not location_ok(loc, mode, a.location_rules):
            return None
    else:  # flat --mode / --city / --us-remote
        if a.mode and mode not in a.mode:
            return None
        if mode == "remote":
            if a.us_remote and not is_us_remote(loc):
                return None
            if a.city and not remote_region_ok(loc, a.city):
                return None
        elif a.city:
            if not any(c in loc.lower() for c in a.city):
                return None
    # salary
    smin, smax = parse_salary(job["text"])
    if a.min_salary and (smax is None or smax < a.min_salary):
        return None
    job.update(mode=mode, visa=v, age_days=age_days, sal=(smin, smax))
    return job

def sal_str(job):
    lo, hi = job.get("sal", (None, None))
    if lo is None:
        return "-"
    return f"${lo//1000}k" if lo == hi else f"${lo//1000}-{hi//1000}k"

# --- main ---------------------------------------------------------------------
def csv_list(s):
    return [x.strip().lower() for x in s.split(",") if x.strip()] if s else []

def main():
    prof = {}
    # prefer a private profile.local.json (git-ignored) over the shared profile.json
    for fname in ("profile.local.json", "profile.json"):
        pf = os.path.join(HERE, fname)
        if os.path.exists(pf):
            prof = json.load(open(pf))
            break

    def d(key, fallback):  # default from profile.json, else fallback
        v = prof.get(key, fallback)
        return [x.lower() for x in v] if isinstance(v, list) else v

    p = argparse.ArgumentParser(
        description="Fresh real jobs from ATS boards. Defaults come from profile.json; "
                    "any flag overrides. Bare `python3 jobhunt.py` uses your profile.")
    p.add_argument("--companies", default=os.path.join(HERE, "companies.json"))
    p.add_argument("--title", type=csv_list, default=d("title", []), help="title keywords (any)")
    p.add_argument("--stack", type=csv_list, default=d("stack", []),
                   help="tech keywords; matches ANY by default")
    p.add_argument("--stack-all", action="store_true", default=d("stack_all", False),
                   help="require ALL --stack keywords instead of any")
    p.add_argument("--exclude", type=csv_list, default=d("exclude", []),
                   help="drop if title contains any (e.g. intern,junior,new grad)")
    p.add_argument("--level", type=csv_list, default=d("level", []),
                   help="keep only if title contains any (e.g. senior,staff,lead)")
    p.add_argument("--mode", type=csv_list, default=d("mode", []), help="remote,hybrid,onsite")
    p.add_argument("--city", type=csv_list, default=d("city", []), help="city substrings (any)")
    p.add_argument("--us-remote", action=argparse.BooleanOptionalAction,
                   default=d("us_remote", False),
                   help="keep only US-based remote roles (drop remote-Canada/EMEA/etc.)")
    p.add_argument("--min-salary", type=int, default=d("min_salary", 0))
    p.add_argument("--max-age", type=float, default=d("max_age", 2),
                   help="max age in days (default 2)")
    p.add_argument("--sponsor-only", action="store_true", default=d("sponsor_only", False),
                   help="only postings that explicitly offer sponsorship")
    p.add_argument("--include-excluded", action="store_true", default=d("include_excluded", False),
                   help="also show citizens-only / no-sponsorship postings")
    p.add_argument("--json", metavar="FILE", default=d("json", None))
    p.add_argument("--csv", metavar="FILE", default=d("csv", None))
    p.add_argument("--html", metavar="FILE", default=d("html", None))
    a = p.parse_args()
    a.location_rules = prof.get("locations")  # profile-only; overrides flat mode/city

    cos = json.load(open(a.companies))["companies"]
    jobs, errors = [], []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(ADAPTERS[c["type"]], c, a): c
                for c in cos if c["type"] in ADAPTERS}
        for f in cf.as_completed(futs):
            c = futs[f]
            try:
                jobs.extend(f.result())
            except Exception as e:
                errors.append(f"{c['name']}: {e}")

    hits = [m for j in jobs if (m := match(j, a))]
    hits.sort(key=lambda j: j["posted"] or "", reverse=True)

    # console
    print(f"\nScanned {len(jobs)} postings from {len(cos)} companies -> "
          f"{len(hits)} match\n" + "=" * 70)
    for j in hits:
        age = f"{j['age_days']:.1f}d" if j["age_days"] is not None else "?"
        print(f"[{age:>5}] {j['company']} — {j['title']}")
        print(f"        {j['mode']:<7} | {j['location'][:45] or '-':<45} | "
              f"visa:{j['visa']:<8} | {sal_str(j)}")
        print(f"        {j['url']}")
    if errors:
        print("\n" + "-" * 70 + f"\n{len(errors)} board(s) failed:")
        for e in errors:
            print("  " + e)

    if a.json:
        json.dump(hits, open(a.json, "w"), indent=2, default=str)
        print(f"\nwrote {a.json}")
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["company", "title", "mode", "location", "visa",
                        "salary", "age_days", "posted", "url"])
            for j in hits:
                w.writerow([j["company"], j["title"], j["mode"], j["location"],
                            j["visa"], sal_str(j),
                            f"{j['age_days']:.1f}" if j["age_days"] is not None else "",
                            j["posted"], j["url"]])
        print(f"wrote {a.csv}")
    if a.html:
        write_html(a.html, hits)
        print(f"wrote {a.html}")

def write_html(path, hits):
    rows = "\n".join(
        f"<tr><td>{h['age_days']:.1f}d</td><td>{html.escape(h['company'])}</td>"
        f"<td><a href='{html.escape(h['url'])}' target='_blank'>{html.escape(h['title'])}</a></td>"
        f"<td>{h['mode']}</td><td>{html.escape(h['location'])}</td>"
        f"<td class='v-{h['visa']}'>{h['visa']}</td><td>{sal_str(h)}</td></tr>"
        for h in hits if h['age_days'] is not None)
    doc = f"""<!doctype html><meta charset=utf-8><title>Job hits</title>
<style>body{{font:14px system-ui;margin:2rem;max-width:1100px}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}}
th{{background:#f4f4f5}}.v-SPONSORS{{color:#15803d;font-weight:600}}.v-silent{{color:#a16207}}
a{{color:#2563eb;text-decoration:none}}</style>
<h2>{len(hits)} fresh matches</h2>
<table><tr><th>Age</th><th>Company</th><th>Role</th><th>Mode</th><th>Location</th><th>Visa</th><th>Salary</th></tr>
{rows}</table>"""
    open(path, "w").write(doc)

if __name__ == "__main__":
    main()
