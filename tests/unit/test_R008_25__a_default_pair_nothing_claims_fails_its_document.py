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

from dossier.domain.conversion import NoConverter, UnclaimedDefault, select, used

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


class JsonMarkdown:
    id = "json-markdown"
    version = "0.1.0"
    media_type = ALERTS
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return payload


PAGE = b"<h1>PLAY-4001</h1><p>Duplicate payment retries</p>"
ALERT_EXPORT = b'{"incident": "PLAY-4006", "alerts": []}'


def _convert(workspace, *, converters, kinds=None):
    from dossier.application.convert import HeldDocument, convert_source
    from dossier.infrastructure.cache import ArtifactCache
    from dossier.infrastructure.store import SnapshotStore

    store = SnapshotStore(workspace)
    documents = {
        "PLAY-4001-payment-retries.html": HeldDocument(
            snapshot=store.put(PAGE), media_type="text/html"
        ),
        "PLAY-4006-indexer-alerts.json": HeldDocument(
            snapshot=store.put(ALERT_EXPORT), media_type=ALERTS
        ),
    }
    return convert_source(
        source_id="incidents-exports",
        documents=documents,
        kinds=kinds,
        converters=converters,
        store=store,
        cache=ArtifactCache(workspace, namespace="convert"),
    )


class TestTheRestOfTheSourceConverts:
    """R8.25 — the application half: one document's failure, with R8.6's shape."""

    def test_only_the_document_nothing_reads_fails(self, tmp_path):
        """Row 1: the one where the page converts and the alerts are named.

        The reason is the one `select` gave, so it names the pair, what is
        claimed and the entry point group -- what someone needs to fix it.
        """
        report = _convert(tmp_path, converters=[HtmlMarkdown()])

        assert report.present == ("PLAY-4001-payment-retries.html",)
        assert report.converted == 1
        (failed,) = report.failed
        assert failed.document == "PLAY-4006-indexer-alerts.json"
        assert "('application/json', 'markdown')" in failed.error
        assert "(text/html, markdown)" in failed.error
        assert "dossier.converters" in failed.error

    def test_a_converter_installed_later_reads_it_and_the_rest_is_cached(self, tmp_path):
        """Row 3: the one where the installation changed and nothing was cached.

        What failed was the installation, not the bytes, so there is no failure
        to remember: the next conversion asks again and finds an answer.
        """
        _convert(tmp_path, converters=[HtmlMarkdown()])

        report = _convert(tmp_path, converters=[HtmlMarkdown(), JsonMarkdown()])

        assert report.failed == ()
        assert report.converted == 1, "the JSON, and only the JSON"
        assert report.cached == 1, "the page, served from cache"

    def test_a_declared_kind_still_stops_the_source(self, tmp_path):
        """Counter-example (row 4): the one where `convert: [markdown]` was written.

        Nothing is converted, the page included (R8.24).
        """
        with pytest.raises(NoConverter):
            _convert(tmp_path, converters=[HtmlMarkdown()], kinds=["markdown"])


class TestAManifestPinsWhatAnswered:
    """R8.25 row 2 — what a run pins when one document had no converter."""

    def test_the_json_pins_nothing_and_the_page_pins_its_converter(self):
        """Row 2: the one where the manifest agrees with what was read.

        No converter read the JSON, so none is part of what the run depended on
        (R8.9). Refusing here instead is what stopped `dossier run` after
        `dossier convert` had already stopped refusing.
        """
        pinned = used(
            requests=[("text/html", None), (ALERTS, None)],
            available=[HtmlMarkdown()],
        )

        assert [converter.id for converter in pinned] == ["html-markdown"]

    def test_a_declared_pair_nothing_claims_is_still_refused(self):
        """Counter-example (row 4): the one where the kind was written down."""
        with pytest.raises(NoConverter):
            used(requests=[(ALERTS, ["markdown"])], available=[HtmlMarkdown()])
