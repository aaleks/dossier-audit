"""Playground converters for PDF snapshots.

Two converters, two kinds, one media type:

    (application/pdf, markdown)     -> pdf-markdown       text a stage can read
    (application/pdf, page_images)  -> pdf-page-images    the images it carries

Neither is part of `dossier`. They are registered through the `dossier.converters`
entry point group, which is the only way a converter is ever resolved (R8.7).
"""

__all__ = ["markdown", "images"]
