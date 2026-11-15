# Your scraper is lying to you (and it's your fault)

*A field note on the most expensive bug in data collection.*

---

Every scraper I've inherited has had the same bug, and it's never the one people worry about.

It's not the anti-bot layer. It's not the CAPTCHA. It's not even the site redesign.

**It's that when the site changes, the scraper returns an empty CSV and exits 0.**

## The failure mode

Here is what it looks like from the client's side:

```
Monday    — 847 rows
Tuesday   — 812 rows
Wednesday — 0 rows
Thursday  — 0 rows
Friday    — 0 rows
```

Nobody notices for three weeks.

The cron job ran. Exit code was 0. No alerts fired. The file was delivered on time, every day, containing nothing.

By the time anyone asks, you've lost three weeks of data that can't be recovered — because the source page is now different, and the historical snapshot you needed was never captured.

## Why people write scrapers this way

Because an empty result *is* a legitimate outcome in scraping.

The page might genuinely have no new listings. The account might legitimately have zero orders. The RSS feed might honestly be empty today.

So the code does this:

```python
rows = parse(html)
if not rows:
    return []        # "no data today, I guess"
```

And that looks reasonable — right up until the day `parse()` silently returns `[]` because a CSS selector changed.

Now you can't tell the difference between:

- **"There is nothing"** — a fact about the world
- **"I could not read it"** — a fact about your code

## The fix

Distinguish them at the point where the ambiguity is created.

```python
def fetch_list(page):
    html = get(page)
    rows = parse(html)
    if not rows:
        # Was the page itself empty, or did parsing fail?
        if "results" not in html and "list" not in html:
            raise ScrapeError(
                f"list container missing on {page} — "
                f"site structure changed, not 'no data'"
            )
    return rows
```

The principle: **an empty result must be proven, not assumed.**

If the page has a results container and it's empty, that's real emptiness. If the container itself has vanished, that's a structural failure and should stop the pipeline.

## Three other things that came from the same lesson

### 1. Emit a heartbeat, not just data

Send a weekly message even when nothing changed:

> Week 42: 1,204 rows fetched, 0 new after dedupe. Upstream unchanged.

"No change" is information. Silence is not.

This single habit has saved me more client relationships than any performance optimisation.

### 2. Make every row traceable

Every output row carries `source_url` and `fetched_at`. Not because it's required, but because when a client says "this number looks wrong," you can check in ten seconds instead of an hour.

### 3. Score the output, and show your work

If your pipeline classifies anything — intent, quality, priority — emit the reasons alongside the verdict.

```json
{"grade": "A", "signals": ["explicit-budget", "contact-present", "recent"]}
```

A grade without evidence is a black box. Clients either trust it blindly or ignore it. Neither is what you want.

## The uncomfortable part

The clients who care about this are not the ones who ask for the cheapest quote.

The cheapest quote assumes the scraper works forever. The realistic quote assumes it breaks, and prices the response.

**Selling "it will break and here's what happens then" is harder than selling "it works." But it's the only version that survives contact with a real website.**

---

*The pipeline described here runs on Hacker News' public API and is open source. It's deliberately small — 200 lines, no dependencies — because the point is the error handling, not the parsing.*
