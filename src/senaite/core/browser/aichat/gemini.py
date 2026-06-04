# -*- coding: utf-8 -*-
"""Gemini REST client + Zope catalog query helpers for ATLAS.

Python 2.7 compatible (uses urllib2). Returns a clear data-grounded
fallback when GEMINI_API_KEY is unset OR when Gemini is unreachable, so
the user always gets the catalog facts even if the LLM is down.
"""
import json
import os
import re
import time
from collections import OrderedDict

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

# Transient HTTP codes worth retrying.
_RETRY_CODES = (429, 500, 502, 503, 504)


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


# Human-friendly labels for SENAITE workflow states. Used so ATLAS can
# answer "is it pending or approved" without the user knowing SENAITE
# internals.
STATE_LABELS = {
    "to_be_sampled":       "To be sampled",
    "scheduled_sampling":  "Scheduled for sampling",
    "sample_due":          "Sample due (awaiting reception)",
    "sample_received":     "Sample received - in progress",
    "to_be_preserved":     "To be preserved",
    "to_be_verified":      "To be verified (PENDING approval)",
    "verified":            "Verified (APPROVED)",
    "published":           "Published (APPROVED & released)",
    "invalid":             "Invalid",
    "rejected":            "Rejected",
    "cancelled":           "Cancelled",
    "dispatched":          "Dispatched",
    "stored":              "Stored",
    "active":              "Active",
    "inactive":            "Inactive",
    "registered":          "Registered",
    "assigned":            "Assigned to worksheet",
    "unassigned":          "Unassigned",
}


def friendly_state(state):
    if not state:
        return None
    return STATE_LABELS.get(state, state.replace("_", " ").capitalize())


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
    out = OrderedDict()
    for label, ptype in SUMMARY_TYPES:
        out[label] = _count_in_catalogs(cats, ptype)
    return out


# ---------------------------------------------------------------------------
# Value serialization
# ---------------------------------------------------------------------------

def _call(obj, name):
    """getattr + call-if-callable, swallowing errors. Returns raw value."""
    try:
        v = getattr(obj, name, None)
        if callable(v):
            v = v()
        return v
    except Exception:
        return None


def _to_text(value):
    """Coerce any value to clean unicode, recovering from mixed
    utf-8/latin-1 byte strings (SENAITE units like 'mm\xc2\xb2')."""
    if isinstance(value, bytes):  # py2 str
        for enc in ("utf-8", "latin-1"):
            try:
                return value.decode(enc)
            except Exception:
                continue
        return value.decode("utf-8", "replace")
    try:
        return unicode(value)  # noqa: F821 (py2)
    except Exception:
        try:
            return str(value).decode("utf-8", "replace")
        except Exception:
            return u""


def _serialize_value(value):
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    if value is None or value == "":
        return None
    s = _to_text(value).strip()
    if not s or s.startswith(u"<bound method") or s.startswith(u"<"):
        return None
    return s[:300]


# Curated, logically ordered accessors. Remarks/Progress/Status/Creator are
# handled specially in enrich_hits, so they are intentionally not here.
DETAIL_ATTRS = [
    "Title", "Description",
    # Identity / sample
    "getRequestID", "getClientSampleID", "getClientOrderNumber",
    "getClientReference",
    # Client / contact
    "getName", "getClientID", "getClientTitle",
    "getContactFullName", "getEmailAddress", "getPhone", "getMobilePhone",
    "getTaxNumber",
    # Sample meta
    "getSampleTypeTitle", "getSamplePointTitle",
    "getDateSampled", "getDateReceived", "getDatePublished",
    "getDateVerified", "getSamplingDate",
    "getPriority",
    # Address-ish
    "getCountry", "getCity", "getProvince", "getPostalCode",
]


def object_details(obj):
    """Pull a clean ordered dict of common SENAITE fields."""
    out = OrderedDict()
    for name in DETAIL_ATTRS:
        try:
            v = _serialize_value(getattr(obj, name, None))
            if v:
                out[name] = v
        except Exception:
            continue
    return out


def _creator_name(obj):
    """Resolve the full name of whoever created the object."""
    uid = _call(obj, "Creator")
    if not uid:
        return None
    uid = str(uid)
    try:
        mt = getToolByName(obj, "portal_membership", None)
        member = mt.getMemberById(uid) if mt else None
        if member is not None:
            full = member.getProperty("fullname", "") or ""
            if full:
                return "%s (%s)" % (full, uid)
    except Exception:
        pass
    return uid


def _fmt_date(value):
    if value is None:
        return None
    try:
        s = str(value)
    except Exception:
        return None
    return s[:19]


def _extract_remarks(obj):
    """SENAITE 2.x stores remarks as a list of records. Older content
    stores a plain string. Return a readable, dated transcript."""
    raw = _call(obj, "getRemarks")
    if not raw:
        return None
    # New-style Remarks object exposing .records
    records = getattr(raw, "records", None)
    if records:
        lines = []
        for rec in records:
            try:
                who = rec.get("user_name") or rec.get("user_id") or "?"
                when = _fmt_date(rec.get("created")) or ""
                content = (rec.get("content") or "").strip()
                if content:
                    lines.append("[%s %s] %s" % (when, who, content))
            except Exception:
                continue
        if lines:
            return " || ".join(lines)
    # Fallback: plain string / unicode
    try:
        s = unicode(raw).strip()  # noqa: F821 (py2)
    except Exception:
        s = str(raw).strip()
    return s[:600] or None


def _analysis_summary(obj, limit=40):
    """For a sample, list its analyses and flag out-of-range anomalies.
    Returns (rows, anomalies) or None when the object has no analyses."""
    getter = getattr(obj, "getAnalyses", None)
    if not callable(getter):
        return None
    try:
        analyses = getter(full_objects=True)
    except Exception:
        try:
            analyses = getter()
        except Exception:
            return None
    rows = []
    anomalies = []
    for an in (analyses or [])[:limit]:
        try:
            title = _serialize_value(getattr(an, "Title", None)) \
                or _to_text(_call(an, "getKeyword") or "Analysis")
            result = _call(an, "getFormattedResult") or _call(an, "getResult")
            unit = _call(an, "getUnit") or ""
            oor = False
            try:
                flag = an.isOutOfRange()
                oor = bool(flag[0]) if isinstance(flag, (list, tuple)) else bool(flag)
            except Exception:
                oor = False
            state = friendly_state(_call(an, "review_state")
                                   or _call(an, "getReviewState"))
            result_s = u"" if result in (None, "") else _to_text(result)
            row = (u"%s = %s %s" % (_to_text(title), result_s,
                                    _to_text(unit))).strip()
            if state:
                row += " [%s]" % state
            if oor:
                row += " *** OUT OF RANGE ***"
                anomalies.append(row)
            # also surface per-analysis remarks as anomaly signal
            arem = _extract_remarks(an)
            if arem:
                note = "%s remark: %s" % (title, arem)
                rows.append(note)
                anomalies.append(note)
            rows.append(row)
        except Exception:
            continue
    return rows, anomalies


def enrich_hits(context, hits, max_objs=6):
    """For the first `max_objs` hits, fetch the object and attach a
    `details` dict with real field values, status, progress, creator,
    remarks and any out-of-range anomalies."""
    root = context.getPhysicalRoot()
    for hit in hits[:max_objs]:
        path = hit.get("path") or ""
        ptype = hit.get("portal_type", "")
        if ptype in ("Plone Site", "Setup"):
            hit["details"] = OrderedDict()
            continue
        try:
            obj = root.restrictedTraverse(path.lstrip("/"))
        except Exception:
            hit["details"] = OrderedDict()
            continue

        details = object_details(obj)

        # Status (human readable)
        rs = hit.get("review_state") or _call(obj, "review_state")
        fs = friendly_state(rs)
        if fs:
            details["Status"] = fs

        # Progress %
        prog = _call(obj, "getProgress")
        if prog not in (None, ""):
            try:
                details["Progress"] = "%d%%" % int(round(float(prog)))
            except Exception:
                details["Progress"] = "%s%%" % prog

        # Who created it and when
        cname = _creator_name(obj)
        if cname:
            details["Created by"] = cname
        cdate = _fmt_date(_call(obj, "created"))
        if cdate:
            details["Created on"] = cdate

        # Remarks transcript
        rem = _extract_remarks(obj)
        if rem:
            details["Remarks"] = rem

        # Analyses + anomalies (samples only)
        ana = _analysis_summary(obj)
        if ana:
            rows, anomalies = ana
            if rows:
                details["Analyses"] = " | ".join(rows[:25])
            if anomalies:
                details["Anomalies"] = " | ".join(anomalies[:25])

        hit["details"] = details
    return hits


# ---------------------------------------------------------------------------
# Search: exact-ID first, then keyword listing, then SearchableText
# ---------------------------------------------------------------------------

# Tokens that look like SENAITE IDs, e.g. TMT8-0009, WS-0003, B-0007, AR-0001.
_ID_RE = re.compile(r"[A-Za-z]{1,8}\d[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
# Indexes that identify the record ITSELF. Deliberately excludes
# getRequestID: on Analysis objects that index equals the parent sample's
# ID, so including it would flood the results with a sample's child
# analyses and push the sample record itself off the list.
_ID_INDEXES = ("getId", "id", "getClientSampleID")


def _id_tokens(query):
    tokens = set()
    for m in _ID_RE.findall(query or ""):
        if any(c.isdigit() for c in m) and len(m) >= 3:
            tokens.add(m)
            tokens.add(m.upper())
    return list(tokens)


def search_catalog(context, query, limit=10):
    """Search across every SENAITE catalog.

    Priority order so a named record is *always* surfaced:
      0) exact-ID lookup on getId/id/getRequestID/getClientSampleID
      1) keyword -> portal_type listing (e.g. "list clients")
      2) SearchableText match
    """
    cats = _catalogs(context)
    if not cats:
        return []

    hits = []
    seen = set()

    def push(brain, front=False):
        try:
            path = brain.getPath()
        except Exception:
            return
        if path in seen:
            return
        seen.add(path)
        rec = {
            "title": getattr(brain, "Title", "") or getattr(brain, "id", ""),
            "path": path,
            "portal_type": getattr(brain, "portal_type", ""),
            "review_state": getattr(brain, "review_state", ""),
            "modified": str(getattr(brain, "modified", "") or ""),
        }
        if front:
            hits.insert(0, rec)
        else:
            hits.append(rec)

    # 0) EXACT-ID lookup -- the record whose own id matches the token.
    tokens = _id_tokens(query)
    tokens_up = set(t.upper() for t in tokens)
    primary = []
    prim_seen = set()
    for token in tokens:
        for cat in cats:
            for index in _ID_INDEXES:
                try:
                    brains = cat(**{index: token})
                except Exception:
                    continue
                for b in brains[:5]:
                    try:
                        p = b.getPath()
                    except Exception:
                        continue
                    if p in prim_seen:
                        continue
                    prim_seen.add(p)
                    primary.append(b)

    # An exact title/id match (the sample itself) ranks before anything
    # else that happened to match, so it is never truncated away.
    def _rank(b):
        t = getattr(b, "Title", "") or getattr(b, "id", "") or ""
        return 0 if str(t).upper() in tokens_up else 1
    primary.sort(key=_rank)
    for b in primary:
        push(b)

    # 1) keyword -> portal_type listing
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
    if len(hits) < limit:
        for word, types in KEYWORDS.items():
            if word in q:
                for t in types:
                    for cat in cats:
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


# ---------------------------------------------------------------------------
# Prompt assembly + Gemini client
# ---------------------------------------------------------------------------

def _format_context(summary, context_hits):
    summary_lines = []
    for k, v in (summary or {}).items():
        summary_lines.append(u"  - {label}: {n}".format(label=k, n=v))

    hit_lines = []
    for hit in (context_hits or []):
        hit_lines.append(
            u"  - {title} (type={type}, path={path})".format(
                title=hit.get("title"),
                type=hit.get("portal_type"),
                path=hit.get("path"),
            )
        )
        details = hit.get("details") or {}
        for k, v in details.items():
            hit_lines.append(u"      {k}: {v}".format(k=k, v=v))
    return summary_lines, hit_lines


def _structured_reply(message, context_hits, summary, note=""):
    """Deterministic, data-grounded answer used when Gemini is
    unavailable. Never fabricates -- only echoes catalog facts."""
    out = []
    if note:
        out.append(note)
    rich = [h for h in (context_hits or []) if h.get("details")]
    if rich:
        for h in rich[:3]:
            out.append("**%s** (%s)" % (h.get("title"), h.get("portal_type")))
            for k, v in (h.get("details") or {}).items():
                out.append("- %s: %s" % (k, v))
            out.append("")
    else:
        out.append("Site totals:")
        for k, v in (summary or {}).items():
            out.append("- %s: %s" % (k, v))
    return "\n".join(out).strip()


class GeminiClient(object):
    """Minimal Gemini REST client with retry + data fallback."""

    def __init__(self, api_key=None, endpoint=GEMINI_ENDPOINT):
        self.api_key = (api_key or "").strip()
        self.endpoint = endpoint

    @classmethod
    def from_env(cls):
        return cls(api_key=os.environ.get("GEMINI_API_KEY", ""))

    def has_key(self):
        return bool(self.api_key)

    def _system_prompt(self, summary, context_hits):
        summary_lines, hit_lines = _format_context(summary, context_hits)
        return (
            "You are ATLAS, an assistant embedded in a SENAITE LIMS "
            "(laboratory information management system). Answer ONLY from "
            "the live catalog data below -- never invent records, results "
            "or names. Be concise and use short markdown (bold labels, "
            "bullet lists).\n\n"
            "Domain rules:\n"
            "- Sample IDs look like TMT8-0009 / AR-0001. If asked about a "
            "specific ID, find it in SEARCH RESULTS and report its fields.\n"
            "- 'Status' tells you the workflow state. 'to_be_verified' "
            "means PENDING approval; 'verified' or 'published' means "
            "APPROVED. Answer pending/approved questions from Status.\n"
            "- 'Progress' is the completion percentage of the sample's "
            "analyses.\n"
            "- 'Created by' / 'Created on' answer who registered a record "
            "and when.\n"
            "- 'Remarks' is the dated remark transcript. 'Anomalies' lists "
            "out-of-range analyses. Use these to flag problems.\n"
            "- For 'how many X' use COUNTS. If the data does not cover the "
            "question, say so plainly.\n\n"
            "COUNTS (entire site):\n"
            + ("\n".join(summary_lines) or "  (no data)") + "\n\n"
            "SEARCH RESULTS (related to current query):\n"
            + ("\n".join(hit_lines) or "  (no matches)")
        )

    def chat(self, message, context_hits=None, summary=None):
        if not self.has_key():
            return _structured_reply(
                message, context_hits, summary,
                note="(ATLAS offline mode - GEMINI_API_KEY not set. "
                     "Showing raw catalog data.)")

        system_prompt = self._system_prompt(summary, context_hits)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": message}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"temperature": 0.2},
        }
        url = "{ep}?key={key}".format(ep=self.endpoint, key=self.api_key)
        data = json.dumps(payload).encode("utf-8")

        last_err = None
        for attempt in range(3):
            req = Request(url, data=data,
                          headers={"Content-Type": "application/json"})
            try:
                resp = urlopen(req, timeout=30)
                body = json.loads(resp.read().decode("utf-8"))
                candidates = body.get("candidates") or []
                if candidates:
                    parts = (candidates[0].get("content") or {}).get("parts") or []
                    text = "".join(p.get("text", "") for p in parts).strip()
                    if text:
                        return text
                last_err = "empty response"
            except HTTPError as exc:
                last_err = "HTTP %s" % exc.code
                if exc.code in _RETRY_CODES and attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                break
            except URLError as exc:
                last_err = "network %s" % exc.reason
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_err = str(exc)
                break

        # Gemini failed -> still answer from the data we fetched.
        return _structured_reply(
            message, context_hits, summary,
            note="(ATLAS: AI service busy [%s] - here is the catalog "
                 "data directly.)" % last_err)
