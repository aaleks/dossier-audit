"""R0.13 — a `per_part` step writes each part under its document.

R0.11 gives every artifact `runs/<run_id>/<step>/<document>.json`. A `per_part`
step produces several artifacts for one document (R3.12), so the document
becomes a directory and each part is a file in it.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.store import output_path

RUN = "20260806T142203Z-4f1a"
PDF = "INC-4830-postmortem-checkout-tls-expiry.pdf"


class TestAPartIsFiledUnderItsDocument:
    """R0.13 — one more level, and only for a step that needs it."""

    def test_a_part_is_a_file_inside_its_documents_directory(self):
        """Example 1: the one an auditor navigates.

        `.md` because a describe step declares no `output` and what a person
        opens is what the model wrote, exactly as R0.11 already decides for a
        report step.
        """
        assert (
            output_path("describe", PDF, structured=False, part="page-001.png")
            == f"describe/{PDF}/page-001.md"
        )

    def test_the_documents_key_is_a_directory_name_exactly_as_it_is_a_file_name(self):
        """Example 2: the one where the key carries an extension.

        `audit-note.pdf` is a directory here and a file name in R0.11, and in
        both cases it is the key as the source gave it. Stripping `.pdf` to make
        a tidier directory would collide `audit-note.pdf` with `audit-note.md`,
        which R4.10 says are two documents.
        """
        path = output_path("describe", "audit-note.pdf", structured=False, part="page-002.png")

        assert path == "describe/audit-note.pdf/page-002.md"

    def test_the_parts_suffix_is_replaced_rather_than_appended(self):
        """The one where a part would otherwise be `page-001.png.md`.

        A part name comes from the container, where it carries the suffix of
        what it holds (R8.11). What is written here is the model's answer about
        that part, not the part -- so the artifact is named after the page and
        carries the artifact's own extension.
        """
        assert output_path("describe", PDF, structured=False, part="page-003.png").endswith(
            "page-003.md"
        )

    def test_a_structured_per_part_step_still_writes_json(self):
        """The one where a describe step declares an output after all.

        Nothing about `per_part` says the answer must be prose. The extension
        follows the schema, as it does for every other mode (R0.11).
        """
        assert output_path("describe", PDF, structured=True, part="page-001.png") == (
            f"describe/{PDF}/page-001.json"
        )

    def test_a_step_with_no_part_is_filed_exactly_where_it_always_was(self):
        """Counter-example (row 4): the one R0.11 still describes.

        Every `per_file` and `aggregate` step. R0.13 adds a level for the mode
        that needs one and changes nothing for the two that do not -- if this
        moved, every path in every spec that names an artifact would be wrong.
        """
        assert output_path("extract", "INC-4821", structured=True) == "extract/INC-4821.json"
        assert output_path("report", "*", structured=False) == "report/aggregate.md"
