# Contributing

The most valuable contribution is **adding companies** to `companies.json`. The
tool is only as good as its list of direct-employer ATS boards, and that list
benefits most from many people adding the companies they find.

## Add a company (Greenhouse / Lever / Ashby)

1. Find the company's careers page and confirm the ATS from its URL:
   - `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>` → `greenhouse`
   - `jobs.lever.co/<token>` → `lever`
   - `jobs.ashbyhq.com/<token>` → `ashby`
2. Add one entry to `companies.json`:
   ```json
   {"name": "Acme", "type": "greenhouse", "token": "acme"}
   ```
   `token` is the slug in the URL above.
3. Verify it returns jobs before opening the PR:
   ```bash
   # greenhouse
   curl -s "https://boards-api.greenhouse.io/v1/boards/acme/jobs" | head -c 200
   # ashby
   curl -s "https://api.ashbyhq.com/posting-api/job-board/acme" | head -c 200
   # lever
   curl -s "https://api.lever.co/v0/postings/acme?mode=json" | head -c 200
   ```

## Add a company (Workday)

Workday site slugs are arbitrary, so don't guess. Grab the real careers URL
(click Careers until you land on `*.myworkdayjobs.com/...`) and let the helper
validate + append it:

```bash
python3 wd_add.py --name "Acme" "https://acme.wd1.myworkdayjobs.com/External"
```

That writes the correct `{tenant, host, site}` into `companies.json`.

## Guidelines

- **Direct employers only.** No staffing agencies, recruiters, or job-board
  aggregators — only a company posting its own roles.
- **No duplicates.** Check the company isn't already listed.
- **Keep entries sorted-ish** by type then name (not required, but nice).
- One PR can add many companies. In the PR description, note that each board
  returned live jobs when you checked.

## Code changes

Bug fixes and new filters are welcome. Keep the tool **dependency-free**
(standard library only) so it stays a clone-and-run script. Test with:

```bash
python3 jobhunt.py --max-age 7
```
