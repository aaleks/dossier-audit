"""R4.10 — a document key two sources both hold stops the run, naming both.

A run covers a set of documents, and a key identifies one of them. Two sources
holding the same key make that untrue, and nothing downstream can tell which
document a finding was about.

Found by `/quality`. The CLI assembled documents with `text.update()` and
`documents.update()`, so two sources both holding `README.md` collapsed to one
entry and the source listed last in `sources:` won. The other document was
audited by nobody, reported nowhere, and reordering the `sources:` list changed
the run's answer with nothing in the diff to explain it.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.sync import DocumentCollision, one_document_per_key


class TestAKeyIdentifiesOneDocument:
    """R4.10 — two sources cannot both mean `INC-4821`."""

    def test_a_key_two_sources_hold_is_refused_naming_both(self):
        """Example 1: the one where the same incident is in Jira and in a folder."""
        with pytest.raises(DocumentCollision) as error:
            one_document_per_key(
                {
                    "incidents-jira": ["INC-4821", "INC-4822"],
                    "incidents-manual": ["INC-4821", "audit-note.pdf"],
                }
            )

        message = str(error.value)
        assert "INC-4821" in message
        assert "incidents-jira" in message and "incidents-manual" in message
        assert "INC-4822" not in message, "only the colliding key is named"

    def test_distinct_keys_across_sources_are_the_normal_case(self):
        """Example 3: the one where two sources coexist happily.

        Without this row the rule is satisfied by refusing every pipeline with
        more than one source, which is most of them.
        """
        one_document_per_key(
            {
                "incidents-jira": ["INC-4821"],
                "procedures-confluence": ["OPS-114"],
            }
        )

    def test_one_source_read_twice_is_not_a_collision(self):
        """Counter-example (row 4): the one where a source appears in both lists.

        A pipeline may name the same source under `sources:` and `reference:`.
        That is one source read twice, not two documents disagreeing, and R2.12
        already syncs it once.
        """
        one_document_per_key({"procedures-confluence": ["OPS-114", "OPS-115"]})

    def test_every_colliding_key_is_named_not_just_the_first(self):
        """The one where a whole directory was duplicated.

        Someone who copied a source wants the list, not one example and another
        run to find the next.
        """
        with pytest.raises(DocumentCollision) as error:
            one_document_per_key(
                {
                    "a": ["INC-4821", "INC-4822", "OPS-114"],
                    "b": ["INC-4821", "INC-4822"],
                }
            )

        message = str(error.value)
        assert "INC-4821" in message and "INC-4822" in message
        assert "OPS-114" not in message

    def test_the_message_does_not_depend_on_source_order(self):
        """The one that keeps the refusal itself deterministic.

        A message assembled from an unordered set would differ between machines,
        which is the class of bug this project spends most of its checks on
        (R0.4, R5.6).
        """
        forwards = {"alpha": ["INC-4821"], "beta": ["INC-4821"]}
        backwards = {"beta": ["INC-4821"], "alpha": ["INC-4821"]}

        with pytest.raises(DocumentCollision) as first:
            one_document_per_key(forwards)
        with pytest.raises(DocumentCollision) as second:
            one_document_per_key(backwards)

        assert str(first.value) == str(second.value)
