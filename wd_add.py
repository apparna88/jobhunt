#!/usr/bin/env python3
"""
Add Workday companies to companies.json from their real careers URLs.

Workday site slugs are arbitrary, so guessing them doesn't work. Instead, grab the
actual URL: on a company's site click "Careers"/"Jobs" until you land on a page like
  https://<tenant>.wd5.myworkdayjobs.com/en-US/<Site>/...
Copy that URL and pass it here. The script parses tenant/host/site, VALIDATES it
against the jobs API, and appends it to companies.json (skips dupes / invalid).

Usage:
  cd ~/jobhunt
  python3 wd_add.py "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite" ...
  python3 wd_add.py --name "DoorDash" "https://doordash.wd1.myworkdayjobs.com/Doordashcareers"
  python3 wd_add.py --file urls.txt         # one URL per line; optional "Name | URL"
"""
import argparse, json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "jobhunt/1.0", "Content-Type": "application/json"}
URL_RE = re.compile(
    r"https?://([a-z0-9-]+)\.(wd\d+[a-z]?)\.myworkdayjobs\.com/([^?#]+)", re.I)

def parse(url):
    m = URL_RE.search(url.strip())
    if not m:
        return None
    tenant, host, path = m.group(1).lower(), m.group(2).lower(), m.group(3)
    segs = [s for s in path.split("/") if s]
    # drop a leading locale like en-US / en_US
    if segs and re.fullmatch(r"[a-z]{2}([-_][a-z]{2})?", segs[0], re.I):
        segs = segs[1:]
    # site is the segment before any /job/... part
    site = segs[0] if segs else None
    return (tenant, host, site) if site else None

def validate(tenant, host, site):
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    req = urllib.request.Request(
        url, data=b'{"limit":1,"offset":0,"searchText":""}', headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("total", 0)
    except Exception as e:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--name", help="display name (single URL only)")
    ap.add_argument("--file", help="file with one URL (or 'Name | URL') per line")
    a = ap.parse_args()

    entries = []  # (name_or_None, url)
    for u in a.urls:
        entries.append((a.name, u))
    if a.file:
        for ln in open(a.file):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if "|" in ln:
                nm, u = ln.split("|", 1)
                entries.append((nm.strip(), u.strip()))
            else:
                entries.append((None, ln))
    if not entries:
        ap.print_help()
        return

    cf_path = os.path.join(HERE, "companies.json")
    doc = json.load(open(cf_path))
    have = {(c["type"], c.get("tenant") or c.get("token")) for c in doc["companies"]}
    added = 0
    for name, url in entries:
        p = parse(url)
        if not p:
            print(f"SKIP  bad URL: {url}")
            continue
        tenant, host, site = p
        if ("workday", tenant) in have:
            print(f"DUP   {tenant} already present")
            continue
        tot = validate(tenant, host, site)
        if not tot:
            print(f"FAIL  {tenant}.{host}/{site} -> no jobs (wrong site slug?) {url}")
            continue
        disp = name or tenant.capitalize()
        doc["companies"].append({"name": disp, "type": "workday",
                                 "tenant": tenant, "host": host, "site": site})
        have.add(("workday", tenant))
        added += 1
        print(f"OK    {disp:<22} {tenant}.{host}/{site}  ({tot} jobs)")

    doc["companies"].sort(key=lambda r: (r["type"], r["name"].lower()))
    json.dump(doc, open(cf_path, "w"), indent=2)
    print(f"\nAdded {added} -> companies.json (now {len(doc['companies'])} total)")

if __name__ == "__main__":
    main()
