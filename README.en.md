# leadpipe — a scraper that fails loudly

A single-file, zero-dependency Python pipeline: **fetch → structure → score intent → export CSV**.

Swap the target site by editing one dict. No code changes.

```bash
python3 leadpipe.py --source hn --limit 60 --out leads.csv
```

Real output:

```
output: leads.csv
total 60 | A 1 | B 0 | C 59 | failed 0
```

Live demo: `h2697930443-hub.github.io/exposure-report/leadpipe.html`

---

## Why this exists

Most scrapers I've inherited had the same bug: **when the site changed, they returned an empty CSV and exited 0.**

The cron job kept running. The client kept receiving empty files. Nobody noticed for three weeks.

This pipeline is built around not doing that.

---

## Four design decisions

### 1. Fail loudly — never return an empty table

If the list endpoint returns nothing, the process **exits non-zero and says so**:

```
ERROR: list endpoint returned 0 rows — this is an exception, not "no data today"
```

An empty result is ambiguous. An exception is not.

### 2. Idempotent by construction

```
unique_key = md5(source + original_id)
```

Run it hourly, daily, or twice by accident — no duplicate rows. The database stops growing out of control.

### 3. Explainable scoring

Every row carries a `signals` field listing which rules fired:

| unique_key | source_url | title | intent_grade | intent_score | signals |
|---|---|---|---|---|---|
| 9ca13807… | news.ycombinator.com/item?id=… | Generative AI uses more energy… | C | 2 | tech-keyword-match |
| a8b6b2fb… | news.ycombinator.com/item?id=… | Lovable apps expose passport details… | C | 2 | tech-keyword-match |

Clients can audit the grade themselves. It is not a black box they have to trust.

### 4. Configuration over code

Each source is one dict entry: a list endpoint plus a detail endpoint. Adding a platform is adding a config, not writing a fetcher.

This also means when something breaks, you can tell within seconds whether it's a config error or a parsing error.

---

## Output schema

| field | purpose |
|---|---|
| `unique_key` | dedupe key, stable across runs |
| `source_url` | every row traceable to origin |
| `title` | raw, unmodified |
| `intent_grade` | A / B / C |
| `intent_score` | 0–10 |
| `signals` | why this grade — human-readable |
| `fetched_at` | ISO 8601 UTC |

---

## What I'd add for a real client

- Scheduler (cron or systemd timer) with alerting on consecutive failures
- Field-level change detection — only emit rows whose tracked fields actually changed
- Retry with backoff on 429/503, and a circuit breaker after N consecutive failures
- A weekly digest email, even when nothing changed ("no new rows, upstream unchanged" is information)

That last one matters more than it sounds. **Clients pay for the thing that tells them nothing is wrong.**

---

## Known limits, stated up front

- No proxy rotation. If the target site rate-limits by IP, this will need one.
- No CAPTCHA handling.
- No JS rendering. Sites that require client-side execution need Playwright.
- Single-threaded. Fine for thousands of rows; not for millions.

I'd rather list these than have someone discover them after paying.

---

## License

MIT.
