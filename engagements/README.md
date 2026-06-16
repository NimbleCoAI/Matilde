# engagements/

This directory holds **per-engagement private data** — query inputs, raw artifacts,
intermediate outputs, and any operational state that is specific to one run or client.

It is **gitignored** by `.gitignore` at the repo root.  Nothing placed here will be
committed, so it is safe to store sensitive operational data here during a live engagement.

## Rename this directory for your domain

`engagements/` is a placeholder name chosen to be neutral.  Rename it to match your
domain's vocabulary before you begin real work:

| Domain | Suggested name |
|---|---|
| Threat intelligence | `cases/` |
| Legal / consulting | `matters/` |
| Journalism | `stories/` |
| Health research | `studies/` |
| Sales / BD | `accounts/` |
| General research | `projects/` |

After renaming, update the path in `.gitignore` and in `sanitize.config.json`
(`sensitive_prefixes` if applicable).

## Suggested layout inside each engagement

```
engagements/
  {{ENGAGEMENT_SLUG}}/        # one dir per engagement, named by you
    artifacts/                # raw archived bytes from collectors (binary, gitignored)
    outputs/                  # processed results, reports, exports
    store.json                # RecordStore backing file (if using engine/)
    notes.md                  # operator notes — never committed
```

Nothing in this directory is ever passed through the sanitization gate
(`scripts/check_sanitization.py`) — that gate operates on committed code and
config only.  Your private operational data never touches it.

## The `.gitkeep` file

The empty `.gitkeep` file at this level exists solely to allow git to track the
directory while it is otherwise empty.  Delete it once you have real content here.
