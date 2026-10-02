"""Connectors: one of the four packages left of the hash boundary.

A network client may be imported here, in `dossier.infrastructure.models`, in
`dossier.infrastructure.tracking` and in `dossier.infrastructure.index`, and
nowhere else (R0.17). This is the one that fetches a source. Credentials live
here and in `dossier.config`, and nowhere else (R1.8).

Connectors are registered through the `dossier.connectors` entry point group and
are never dispatched by a match statement in the core package (R1.7).
"""
