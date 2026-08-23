"""The only package left of the hash boundary.

This is the one place in `dossier` where a network client may be imported
(R0.1). Credentials live here and in `dossier.config`, and nowhere else (R1.8).

Connectors are registered through the `dossier.connectors` entry point group and
are never dispatched by a match statement in the core package (R1.7).
"""
