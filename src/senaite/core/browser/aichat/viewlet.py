# -*- coding: utf-8 -*-
from plone.app.layout.viewlets.common import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class AIChatViewlet(ViewletBase):
    index = ViewPageTemplateFile("templates/viewlet.pt")

    @property
    def endpoint(self):
        return "%s/@@aichat-query" % self.portal_state.portal_url()
