#!/usr/bin/env python3
"""
Discover Workday companies and MERGE them into companies.json.

    cd ~/jobhunt && python3 wd_discover.py

Streams progress live. Probes each tenant across common host/site patterns,
keeps only boards that return real jobs, appends new ones to companies.json.
Add names to TENANTS below (Name|tenant); tenant = the '<tenant>.wdN.myworkdayjobs.com'
subdomain. Tune SITES/HOSTS if a company you know is missed.
"""
import concurrent.futures as cf, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "jobhunt/1.0", "Content-Type": "application/json"}
TIMEOUT = 4          # per request; misses fail fast
HOSTS = ["wd1", "wd5", "wd12", "wd3", "wd101", "wd103"]   # most common pods first

# name|tenant  (add your own lines freely)
TENANTS = """
DoorDash|doordash
Deel|deel
Retool|retool
PayPal|paypal
Mastercard|mastercard
Visa|visa
Cisco|cisco
Dell|dell
VMware|vmware
NetApp|netapp
Splunk|splunk
Autodesk|autodesk
Workday|workday
Palo Alto Networks|paloaltonetworks
Nutanix|nutanix
Roku|roku
eBay|ebay
DocuSign|docusign
SailPoint|sailpoint
Pegasystems|pega
Rapid7|rapid7
Qualys|qualys
Tenable|tenable
Cloudera|cloudera
Informatica|informatica
Teradata|teradata
Micron|micron
Applied Materials|appliedmaterials
Lam Research|lamresearch
Analog Devices|analogdevices
Seagate|seagate
Western Digital|westerndigital
Juniper Networks|juniper
Akamai|akamai
Ciena|ciena
HPE|hpe
Fiserv|fiserv
FIS|fisglobal
Global Payments|globalpayments
Discover|discover
Synchrony|synchrony
BlackRock|blackrock
State Street|statestreet
Fidelity|fidelity
Nasdaq|nasdaq
Thomson Reuters|thomsonreuters
Workiva|workiva
Guidewire|guidewire
Blackbaud|blackbaud
Zscaler|zscaler
Dynatrace|dynatrace
GoDaddy|godaddy
Wix|wix
Pinterest|pinterest
Snap|snap
Roblox|roblox
Zoom|zoom
DoubleVerify|doubleverify
Yext|yext
Unity|unity
Take-Two|taketwo
Electronic Arts|ea
Activision|activision
Warner Bros Discovery|wbd
Paramount|paramount
Comcast|comcast
Adyen|adyen
Klarna|klarna
Marqeta|marqeta
"""

def sites(tenant):
    T = tenant.capitalize()
    return ["External", "External_Career_Site", "External_Careers", "Careers",
            f"{T}_Careers", f"{T}Careers", f"{T}ExternalCareerSite",
            "ExternalCareerSite", "CorporateCareers", f"{tenant}", "careers", "jobs"]

def try_combo(tenant, host, site):
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    req = urllib.request.Request(
        url, data=b'{"limit":1,"offset":0,"searchText":"engineer"}', headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
            if d.get("total", 0) > 0:
                return d["total"]
    except Exception:
        pass
    return None

def discover(item):
    name, tenant = item
    for host in HOSTS:
        for site in sites(tenant):
            tot = try_combo(tenant, host, site)
            if tot:
                return dict(name=name, type="workday", tenant=tenant,
                            host=host, site=site, n=tot)
    return dict(name=name, type=None, tenant=tenant)

def main():
    items = [tuple(x.strip() for x in ln.split("|"))
             for ln in TENANTS.strip().splitlines() if "|" in ln]
    n = len(items)
    print(f"Probing {n} Workday tenants (streaming; ~1-3 min)...\n", flush=True)
    hits, miss, done = [], [], 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(discover, it): it for it in items}
        for f in cf.as_completed(futs):
            r = f.result()
            done += 1
            if r["type"]:
                hits.append(r)
                print(f"[{done}/{n}] FOUND  {r['name']:<22} "
                      f"{r['tenant']}.{r['host']} / {r['site']}  ({r['n']} jobs)", flush=True)
            else:
                miss.append(r)
                print(f"[{done}/{n}] miss   {r['name']}", flush=True)

    hits.sort(key=lambda r: r["name"].lower())
    print(f"\n== {len(hits)} found, {len(miss)} missed ==")

    cf_path = os.path.join(HERE, "companies.json")
    doc = json.load(open(cf_path))
    have = {(c["type"], c.get("tenant") or c.get("token")) for c in doc["companies"]}
    added = 0
    for r in hits:
        if ("workday", r["tenant"]) in have:
            continue
        have.add(("workday", r["tenant"]))
        doc["companies"].append({k: r[k] for k in ("name", "type", "tenant", "host", "site")})
        added += 1
    doc["companies"].sort(key=lambda r: (r["type"], r["name"].lower()))
    json.dump(doc, open(cf_path, "w"), indent=2)
    print(f"Added {added} new -> companies.json (now {len(doc['companies'])} total)")

if __name__ == "__main__":
    main()
