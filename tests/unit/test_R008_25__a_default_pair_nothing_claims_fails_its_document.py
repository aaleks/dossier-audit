"""R8.25 — a document whose default kind nothing converts fails on its own, and
the rest of its source converts.

Who chose the kind decides the blast radius. A source declaring no `convert:`
left the choice to the default table (R8.10), so a pair nothing answers is a
fact about one file somebody attached. A declared kind is configuration, and an
installation that cannot honour it stops the run (R8.24).

`select` is where the two are told apart: both are `NoConverter`, and only the
automatic one is `UnclaimedDefault`. Whatever catches them -- a conversion, a
manifest -- decides the blast radius from the type alone.
"""

from __future__ import annotations

import pytest

from dossier.domain.conversion import NoConverter, UnclaimedDefault, select

ALERTS = "application/json"


class HtmlMarkdown:
    id = "html-markdown"
    version = "1.1.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return payload


class TestTheAutomaticChoiceIsToldApart:
    """R8.25 — the domain half: which unclaimed pairs are one document's problem."""

    def test_a_default_pair_nothing_claims_is_unclaimed_default(self):
        """Row 1: the one where nobody asked for the JSON to be read.

        The message is R8.5's, whole: the pair, what is claimed, and where a
        converter comes from. It is now one document's reason, not the source's.
        """
        with pytest.raises(UnclaimedDefault) as error:
            select(media_type=ALERTS, kinds=None, available=[HtmlMarkdown()])

        message = str(error.value)
        assert "('application/json', 'markdown')" in message
        assert "(text/html, markdown)" in message
        assert "dossier.converters" in message

    def test_a_declared_pair_nothing_claims_is_not(self):
        """Counter-example (row 4): the one where `convert: [markdown]` asked for it.

        Still `NoConverter`, and deliberately not `UnclaimedDefault`: a kind
        written in `sources.yaml` is configuration, and R8.24 stops the run.
        """
        with pytest.raises(NoConverter) as error:
            select(media_type=ALERTS, kinds=["markdown"], available=[HtmlMarkdown()])

        assert not isinstance(error.value, UnclaimedDefault)
