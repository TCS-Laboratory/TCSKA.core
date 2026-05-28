# ATLAS — SENAITE assistant viewlet

`senaite.core.browser.aichat` adds a floating right-side chat button to every page of a SENAITE site. The bot ("ATLAS") answers questions about the live Zope catalog and content, optionally backed by Google's Gemini API for natural-language replies.

## What it does

- **Viewlet** — `AIChatViewlet` registered in `plone.app.layout.viewlets.interfaces.IPortalFooter`. Renders a 56 px circular button bottom-right + slide-up panel.
- **AJAX endpoint** — `BrowserView` registered as `@@aichat-query`, accepts `GET /senaite/@@aichat-query?message=<text>` and returns:
  ```json
  {
    "ok": true,
    "reply": "natural-language answer",
    "summary": { "Clients": 1, "Samples": 0, "Worksheets": 0, ... },
    "context": [ { "title": "...", "path": "...", "details": { ... } }, ... ]
  }
  ```
- **Catalog grounding** — every turn queries 9 SENAITE catalogs (`portal_catalog`, `senaite_catalog`, `senaite_catalog_client`, `senaite_catalog_sample`, `senaite_catalog_analysis`, `senaite_catalog_worksheet`, `senaite_catalog_setup`, `bika_setup_catalog`, `bika_catalog`) and serializes ~30 standard SENAITE accessors from the top 5 results (`getName`, `getEmailAddress`, `getPhone`, `getTaxNumber`, `getClientID`, `getRequestID`, `getDateSampled`, `getSampleTypeTitle`, etc.).
- **No CSRF surface** — read-only `GET`, so `plone.protect` is bypassed entirely.

## Configuration

Single environment variable on the Zope process:

| Variable | Effect |
|---|---|
| `GEMINI_API_KEY` (unset) | Widget still renders. Replies are stub messages including live catalog counts. Useful for confirming wiring. |
| `GEMINI_API_KEY=AIzaSy...` | Real Gemini 2.5 Flash replies grounded in catalog data. |

**The key must never be committed.** Get one from <https://aistudio.google.com/app/apikey>. Keys in `AIzaSy…` format (39 chars) are the right ones; `AQ.Ab…` are OAuth tokens and will be rejected.

Switching the Gemini model: edit `GEMINI_ENDPOINT` in `gemini.py`. Free-tier accessible models currently include `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-flash-lite-latest`. `gemini-2.0-flash` has zero free quota on fresh keys.

## Files

| File | Role |
|---|---|
| `__init__.py` | empty package marker |
| `configure.zcml` | registers viewlet + page (no layer attr, so it resolves on any context inside Zope) |
| `viewlet.py` | `AIChatViewlet`, exposes `endpoint` property |
| `view.py` | `AIChatQueryView` BrowserView at `@@aichat-query` — JSON in/out |
| `gemini.py` | `GeminiClient.from_env()`, `site_summary`, `search_catalog`, `object_details`, `enrich_hits` |
| `templates/viewlet.pt` | floating button + slide-up panel, inline CSS + vanilla JS (no jQuery dependency) |

## Wiring

The parent `senaite/core/browser/configure.zcml` includes this subpackage:

```xml
<include package=".aichat"/>
```

Everything else is self-contained.

## Quick verification

```bash
# Counts + reply (works with or without GEMINI_API_KEY)
curl -u admin:admin "http://localhost:8080/senaite/@@aichat-query?message=how+many+clients"
```

In the browser at `/senaite/`, look for the blue ☀ button bottom-right. Hard-refresh (Ctrl+F5) if the old SENAITE header is cached.

## Customising

- **Rename the bot** — edit `templates/viewlet.pt` (`<header>ATLAS</header>` and `title=`/`placeholder=` strings).
- **Add fields** to detail extraction — append accessor names to `DETAIL_ATTRS` in `gemini.py`.
- **Add type keywords** — extend the `KEYWORDS` dict in `gemini.py:search_catalog`.
- **Restrict who sees it** — add `layer="senaite.core.interfaces.ISenaiteCore"` (or a custom interface) to the `<browser:viewlet>` registration.
