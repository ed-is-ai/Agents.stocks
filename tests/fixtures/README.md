# Test fixtures

Static data files used by the test suite. Load them relative to this directory:

```python
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
raw = (FIXTURES / "stocktwits_weekly_sample.eml").read_text(encoding="utf-8")
```

## Conventions

- **Naming:** `snake_case`, descriptive of the source and shape, e.g.
  `stocktwits_weekly_sample.eml`.
- **Prefer raw `.eml`** for email fixtures (headers + body) so parsers can be
  tested end-to-end — sender/subject matching *and* body extraction. Save a
  sanitised `.html` body only when a full `.eml` can't be scrubbed cleanly.
- **Scrub before committing.** These files may end up in a shared/public repo.
  Remove personal data before adding a fixture:
  - your own email address / name
  - unsubscribe links and per-recipient tokens
  - tracking-pixel URLs and any account-identifying query strings
- **Keep them small and stable** — trim to what the test actually needs.

## Fixtures

- `stocktwits_weekly_sample.eml` — _(to add)_ sample weekly StockTwits "top 25"
  email, used to test IMAP ingestion + ticker parsing (issue #137).
