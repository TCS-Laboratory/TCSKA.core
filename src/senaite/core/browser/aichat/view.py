# -*- coding: utf-8 -*-
import json
import logging

from Products.Five.browser import BrowserView

from .gemini import GeminiClient, enrich_hits, search_catalog, site_summary

logger = logging.getLogger("senaite.core.aichat")


class AIChatQueryView(BrowserView):
    """GET /@@aichat-query?message=... -> JSON {ok, reply, context, summary}."""

    def __call__(self):
        self.request.response.setHeader("Content-Type", "application/json")
        message = (self.request.get("message") or "").strip()
        if not message:
            return json.dumps({"ok": False, "error": "empty message"})

        try:
            summary = site_summary(self.context)
            context_hits = search_catalog(self.context, message, limit=10)
            context_hits = enrich_hits(self.context, context_hits, max_objs=6)

            client = GeminiClient.from_env()
            reply = client.chat(
                message=message,
                context_hits=context_hits,
                summary=summary,
            )
            return json.dumps({
                "ok": True,
                "reply": reply,
                "summary": summary,
                "context": context_hits,
            })
        except Exception as exc:
            logger.exception("aichat-query failed")
            return json.dumps({"ok": False, "error": str(exc)})
