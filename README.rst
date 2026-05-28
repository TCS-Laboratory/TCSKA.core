.. image:: https://raw.githubusercontent.com/senaite/senaite.core/master/static/logo_pypi.png
   :target: https://github.com/senaite/senaite.core
   :alt: senaite.core
   :height: 128px

*Open Source LIMS Core based on the CMS Plone*
==============================================

.. image:: https://img.shields.io/pypi/v/senaite.core.svg?style=flat-square
    :target: https://pypi.python.org/pypi/senaite.core

.. image:: https://img.shields.io/github/actions/workflow/status/senaite/senaite.core/build-and-test.yml?branch=2.x
    :target: https://github.com/senaite/senaite.core/actions/workflows/build-and-test.yml?query=branch:2.x

.. image:: https://img.shields.io/scrutinizer/g/senaite/senaite.core/2.x.svg?style=flat-square
    :target: https://scrutinizer-ci.com/g/senaite/senaite.core/?branch=2.x

.. image:: https://img.shields.io/github/issues-pr/senaite/senaite.core.svg?style=flat-square
    :target: https://github.com/senaite/senaite.core/pulls

.. image:: https://img.shields.io/github/issues/senaite/senaite.core.svg?style=flat-square
    :target: https://github.com/senaite/senaite.core/issues

.. image:: https://img.shields.io/github/contributors/senaite/senaite.core.svg?style=flat-square
    :target: https://github.com/senaite/senaite.core/blob/master/CONTRIBUTORS.rst

.. image:: https://img.shields.io/badge/Built%20with-%E2%9D%A4-red.svg
   :target: https://github.com/senaite/senaite.core

.. image:: https://img.shields.io/badge/Made%20for%20SENAITE-%E2%AC%A1-lightgrey.svg
   :target: https://www.senaite.com


Introduction
============

SENAITE.CORE is an Open Source Laboratory Information Management System (LIMS)
for enterprise environments, especially focused to behave with excellent
performance and stability.


TCSKA fork additions
====================

This is the TCS-Laboratory fork (``TCS-Laboratory/TCSKA.core``). On top of
upstream ``senaite.core``, the ``X.0.2.9_aichat`` branch adds:

* **ATLAS chatbot** — a floating Gemini-backed assistant viewlet that grounds
  every reply in the live Zope catalog. Renders bottom-right on every SENAITE
  page; exposes a JSON endpoint at ``@@aichat-query``.
* **ADYPU header logo** — the default SENAITE site logo
  (``src/senaite/core/browser/static/images/senaite-site-logo.png``) is
  replaced with the ADYPU brand image.

See the package-level guide for setup, configuration, and the JSON shape:
``src/senaite/core/browser/aichat/README.md``.

**Quick start** (assuming you build via the matching ``TCSKA.docker`` image):

.. code-block:: bash

    git clone -b X.0.2.9_aichat https://github.com/TCS-Laboratory/TCSKA.docker.git
    cd TCSKA.docker/X.0.2.9
    docker build -t tcska:X.0.2.9 .
    docker run -d --name tcska -p 8080:8080 \\
        -e GEMINI_API_KEY=AIzaSy....your-key.... \\
        tcska:X.0.2.9

The ``GEMINI_API_KEY`` env var is optional — without it ATLAS still renders
and returns live catalog counts; with it, replies use Gemini 2.5 Flash.
Never commit the key to source control. Get a free key at
https://aistudio.google.com/app/apikey.


Installation
============

SENAITE.CORE provides the core functionalities and entities used by
`SENAITE.LIMS <https://github.com/senaite/senaite.lims>`_.

It is intended to be imported automatically as a dependency of SENAITE.LIMS and
other SENAITE products, and it should **not** be installed without the
SENAITE.LIMS UI.


Contribute
==========

We want contributing to SENAITE.CORE to be fun, enjoyable, and educational for
anyone, and everyone. This project adheres to the `Contributor Covenant
<https://github.com/senaite/senaite.core/blob/master/CODE_OF_CONDUCT.md>`_.

By participating, you are expected to uphold this code. Please report
unacceptable behavior.

Contributions go far beyond pull requests and commits. Although we love giving
you the opportunity to put your stamp on SENAITE.CORE, we also are thrilled to
receive a variety of other contributions.

Please, read `Contributing to senaite.core document
<https://github.com/senaite/senaite.core/blob/master/CONTRIBUTING.md>`_.


Feedback and support
====================

* `Community site <https://community.senaite.org/>`_
* `Gitter channel <https://gitter.im/senaite/Lobby>`_
* `Users list <https://sourceforge.net/projects/senaite/lists/senaite-users>`_


License
=======

**SENAITE.CORE** Copyright (C) 2018-2025 RIDING BYTES & NARALABS

This software, henceforth "SENAITE.CORE" is an add-on for the
`Plone CMS <https://plone.org/>`_ and a derivative work of BIKA LIMS.

This program is free software; you can redistribute it and/or modify it under
the terms of the `GNU General Public License version 2
<https://github.com/senaite/senaite.core/blob/master/LICENSE>`_ as published by
the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
