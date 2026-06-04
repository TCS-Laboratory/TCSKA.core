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
- **Catalog grounding** — every turn queries 9 SENAITE catalogs (`portal_catalog`, `senaite_catalog`, `senaite_catalog_client`, `senaite_catalog_sample`, `senaite_catalog_analysis`, `senaite_catalog_worksheet`, `senaite_catalog_setup`, `bika_setup_catalog`, `bika_catalog`) and serializes standard SENAITE accessors from the top results.
- **Exact-ID lookup first** — when the message contains an ID-shaped token (e.g. `TMT8-0009`, `AR-0001`, `WS-0003`), it is resolved directly via the `getId`/`id`/`getRequestID`/`getClientSampleID` indexes and pushed to the front of the results, so a named record is **always** surfaced (it is no longer crowded out by the most-recently-modified items).
- **Rich record detail** — for each matched object ATLAS extracts and labels:
  - **Status** — workflow state mapped to plain English (`to_be_verified` → "PENDING approval", `verified`/`published` → "APPROVED", etc.).
  - **Progress** — completion percentage from `getProgress()`.
  - **Created by / Created on** — the creator's full name (resolved via `portal_membership`) and timestamp.
  - **Remarks** — the full dated remark transcript (handles the SENAITE 2.x record-list format *and* legacy plain strings).
  - **Anomalies** — scans the sample's analyses and flags any **out-of-range** results plus per-analysis remarks.
- **Resilient replies** — Gemini calls retry 3× with backoff on transient errors (429/500/502/503/504). If the API is still unreachable (or `GEMINI_API_KEY` is unset), ATLAS returns the **raw catalog facts** it already gathered instead of an error string — it never leaves the user empty-handed.
- **No CSRF surface** — read-only `GET`, so `plone.protect` is bypassed entirely.

## What ATLAS can answer

- "How many samples / clients / worksheets do I have?"
- "Tell me about sample TMT8-0009" → full field dump.
- "Is TMT8-0009 pending or approved?" → from **Status**.
- "What's the progress on TMT8-0009?" → from **Progress**.
- "Who created this sample and when?" → from **Created by / Created on**.
- "Show me the remarks on …" / "Are there any anomalies?" → from **Remarks / Anomalies**.

## Configuration

Single environment variable on the Zope process:

| Variable | Effect |
|---|---|
| `GEMINI_API_KEY` (unset) | Widget still renders and answers from the live catalog (raw data fallback, no LLM phrasing). Useful for confirming wiring. |
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

- **Rename the bot** — edit `templates/viewlet.pt` (the `<div class="name">ATLAS</div>` header and the `title=`/`placeholder=` strings).
- **Note on the template** — the inline `<script>` is wrapped in a `//<![CDATA[ … //]]>` block. This is required: the Chameleon engine parses the `.pt` as XML and would otherwise choke on `<`/`>` inside JS regexes and HTML-string literals. Keep the CDATA wrapper when editing the script.
- **Add fields** to detail extraction — append accessor names to `DETAIL_ATTRS` in `gemini.py`.
- **Add type keywords** — extend the `KEYWORDS` dict in `gemini.py:search_catalog`.
- **Restrict who sees it** — add `layer="senaite.core.interfaces.ISenaiteCore"` (or a custom interface) to the `<browser:viewlet>` registration.
