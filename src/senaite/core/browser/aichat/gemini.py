# -*- coding: utf-8 -*-
"""Gemini REST client + Zope portal_catalog query helpers.

Python 2.7 compatible (uses urllib2). Returns a clear placeholder when
GEMINI_API_KEY is unset, so the rest of the chatbot wiring works
end-to-end without a live key.
"""
import json
import os

from Products.CMFCore.utils import getToolByName

try:
    from urllib2 import Request, urlopen, HTTPError, URLError  # py2
except ImportError:  # pragma: no cover - future py3 port
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError


GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

# Portal types ATLAS always reports counts for. Missing types simply
# yield 0 and are dropped from the prompt.
SUMMARY_TYPES = [
    ("Samples",            "AnalysisRequest"),
    ("Samples (new schema)", "Sample"),
    ("Analyses",           "Analysis"),
    ("Analysis Services",  "AnalysisService"),
    ("Worksheets",         "Worksheet"),
    ("Batches",            "Batch"),
    ("Clients",            "Client"),
    ("Contacts",           "Contact"),
    ("Lab Contacts",       "LabContact"),
    ("Instruments",        "Instrument"),
    ("Methods",            "Method"),
    ("Sample Types",       "SampleType"),
    ("Sample Points",      "SamplePoint"),
]


# SENAITE 2.x splits indexes across multiple catalogs. We probe all of
# them per type and take the max non-zero count, since a content type
# is typically registered in exactly one catalog.
CATALOG_NAMES = [
    "portal_catalog",
    "senaite_catalog",
    "senaite_catalog_client",
    "senaite_catalog_sample",
    "senaite_catalog_analysis",
    "senaite_catalog_worksheet",
    "senaite_catalog_setup",
    "bika_setup_catalog",
    "bika_catalog",
]


def _catalogs(context):
    out = []
    for name in CATALOG_NAMES:
        cat = getToolByName(context, name, None)
        if cat is not None:
            out.append(cat)
    return out


def _count_in_catalogs(cats, portal_type):
    best = 0
    for cat in cats:
        try:
            n = len(cat(portal_type=portal_type))
            if n > best:
                best = n
        except Exception:
            continue
    return best


def site_summary(context):
    """Return counts of common SENAITE types across all catalogs."""
    cats = _catalogs(context)
    out = {}
    for label, ptype in SUMMARY_TYPES:
        out[label] = _count_in_catalogs(cats, ptype)
    return out


# Common SENAITE field accessors. Many are methods; we call if callable.
# Order matters for the prompt's readability.
DETAIL_ATTRS = [
    "Title", "Description",
    "getName", "getEmailAddress", "getPhone", "getFax", "getMobilePhone",
    "getClientID", "getTaxNumber", "getBankCode", "getBankAccount",
    "getCountry", "getCity", "getProvince", "getPostalCode", "getAddress",
    "getAccountType", "getAccountName", "getAccountNumber",
    "ClientType", "getClientType",
    # Sample-related
    "getRequestID", "getDateSampled", "getDateReceived",
    "getDatePublished", "getDateVerified",
    "getSampleTypeTitle", "getSampleTypeUID",
    "getClientTitle", "getContactFullName",
    "getCCEmails", "getCCNames",
    "getRemarks", "getPriority",
    "review_state",
]


def _serialize_value(value):
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    if value is None or value == "":
        return None
    try:
        s = str(value)
    except Exception:
        return None
    s = s.strip()
    if not s or s.startswith("<bound method"):
        return None
    return s[:200]


def object_details(obj):
    """Pull a clean dict of common SENAITE fields from a content object."""
    out = {}
    for name in DETAIL_ATTRS:
        try:
            v = _serialize_value(getattr(obj, name, None))
            if v:
                out[name] = v
        except Exception:
            continue
    return out


def enrich_hits(context, hits, max_objs=5):
    """For the first `max_objs` hits, fetch the object and attach a
    `details` dict so Gemini gets real field values, not just metadata."""
    root = context.getPhysicalRoot()
    for hit in hits[:max_objs]:
        path = hit.get("path") or ""
        # Skip portal containers that aren't real records.
        ptype = hit.get("portal_type", "")
        if ptype in ("Plone Site", "Setup"):
            continue
        try:
            obj = root.restrictedTraverse(path.lstrip("/"))
            hit["details"] = object_details(obj)
        except Exception:
            hit["details"] = {}
    return hits


def search_catalog(context, query, limit=10):
    """Heuristic search across every SENAITE catalog.

    1) SearchableText match on the raw query (every catalog).
    2) If the query mentions a known type word, list that type
       (across every catalog) so "list clients" works even when the
       word "client" appears nowhere in the indexed text.
    """
    cats = _catalogs(context)
    if not cats:
        return []

    hits = []
    seen = set()

    def push(brain):
        path = brain.getPath()
        if path in seen:
            return
        seen.add(path)
        hits.append({
            "title": getattr(brain, "Title", "") or brain.id,
            "path": path,
            "portal_type": getattr(brain, "portal_type", ""),
            "review_state": getattr(brain, "review_state", ""),
            "modified": str(getattr(brain, "modified", "") or ""),
        })

    # 1) keyword -> portal_type listing FIRST (most targeted)
    KEYWORDS = {
        "sample":     ["AnalysisRequest", "Sample"],
        "request":    ["AnalysisRequest"],
        "client":     ["Client"],
        "customer":   ["Client"],
        "contact":    ["Contact", "LabContact"],
        "batch":      ["Batch"],
        "worksheet":  ["Worksheet"],
        "analysis":   ["Analysis"],
        "instrument": ["Instrument"],
        "method":     ["Method"],
        "service":    ["AnalysisService"],
    }
    q = (query or "").lower()
    for word, types in KEYWORDS.items():
        if word in q:
            for t in types:
                for cat in cats:
                    brains = []
                    try:
                        brains = cat(portal_type=t, sort_on="modified",
                                     sort_order="reverse",
                                     sort_limit=limit)[:limit]
                    except Exception:
                        try:
                            brains = cat(portal_type=t)[:limit]
                        except Exception:
                            continue
                    for b in brains:
                        push(b)
                        if len(hits) >= limit:
                            break
                    if len(hits) >= limit:
                        break
                if len(hits) >= limit:
                    break
            break

    # 2) SearchableText pass fills remaining slots
    if len(hits) < limit:
        for cat in cats:
            try:
                for b in cat(SearchableText=query, sort_limit=limit)[:limit]:
                    push(b)
                    if len(hits) >= limit:
                        break
            except Exception:
                continue
            if len(hits) >= limit:
                break

    return hits[:limit]


class GeminiClient(object):
    """Minimal Gemini REST client."""

    def __init__(self, api_key=None, endpoint=GEMINI_ENDPOINT):
        self.api_key = (api_key or "").strip()
        self.endpoint = endpoint

    @classmethod
    def from_env(cls):
        return cls(api_key=os.environ.get("GEMINI_API_KEY", ""))

    def has_key(self):
        return bool(self.api_key)

    def chat(self, message, context_hits=None, summary=None):
        if not self.has_key():
            return "(GEMINI_API_KEY not configured)"

        summary_lines = []
        for k, v in (summary or {}).items():
            summary_lines.append("  - {label}: {n}".format(label=k, n=v))

        hit_lines = []
        for hit in (context_hits or []):
            head = (
                "  - {title} (type={type}, state={state}, path={path})"
            ).format(
                title=hit.get("title"),
                type=hit.get("portal_type"),
                state=hit.get("review_state"),
                path=hit.get("path"),
            )
            hit_lines.append(head)
            details = hit.get("details") or {}
            for k, v in details.items():
                hit_lines.append("      {k}: {v}".format(k=k, v=v))

        system_prompt = (
            "You are ATLAS, an assistant embedded in a SENAITE LIMS "
            "instance (laboratory information management system). "
            "Ground every answer in the live Zope catalog data given "
            "below. When the user asks 'how many X', use the COUNTS "
            "section. When asked to list or find items, use SEARCH "
            "RESULTS. If neither covers the question, say so plainly "
            "instead of guessing.\n\n"
            "COUNTS (entire site):\n"
            + ("\n".join(summary_lines) or "  (no data)") + "\n\n"
            "SEARCH RESULTS (related to current query):\n"
            + ("\n".join(hit_lines) or "  (no matches)")
        )

        payload = {
            "contents": [{
                "role": "user",
                "parts": [{"text": message}],
            }],
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
        }
        url = "{ep}?key={key}".format(ep=self.endpoint, key=self.api_key)
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urlopen(req, timeout=30)
            body = json.loads(resp.read().decode("utf-8"))
            candidates = body.get("candidates") or []
            if candidates:
                parts = (candidates[0].get("content") or {}).get("parts") or []
                texts = [p.get("text", "") for p in parts]
                return "".join(texts).strip() or "(empty Gemini response)"
            return "(no Gemini candidates returned)"
        except HTTPError as exc:
            return "(Gemini HTTP error: %s)" % exc.code
        except URLError as exc:
            return "(Gemini network error: %s)" % exc.reason
        except Exception as exc:
            return "(Gemini call failed: %s)" % exc
