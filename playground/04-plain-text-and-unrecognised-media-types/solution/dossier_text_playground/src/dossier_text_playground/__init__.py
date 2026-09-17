"""A playground converter for `text/plain` snapshots.

Registered through the `dossier.converters` entry point group, like every other
converter (R8.7). `dossier` itself ships only `markdown-text`, which claims
`(text/markdown, markdown)` -- a `.txt` note is a different pair and needs its
own claim.
"""

__all__ = ["plain"]
