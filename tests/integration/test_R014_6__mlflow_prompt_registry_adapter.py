"""`MlflowPromptRegistry` maps MLflow's prompt objects onto `PublishedPrompt`.

Spec 013 gives the `PromptRegistry` port two methods and nothing to prove them
against but MLflow itself, so this is an adapter test rather than a rule proof:
it checks the mapping `publish` and `latest` do over a `PromptVersion`, and
that `latest` turns MLflow's "no such prompt" into `None` rather than letting
it propagate.

Nothing here opens a socket: both `mlflow.genai.register_prompt` and
`MlflowClient.search_prompt_versions` are replaced, so the autouse fixture in
`tests/conftest.py` that blocks `socket.socket` never fires and is left in
place.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dossier.domain.prompts import PublishedPrompt
from dossier.infrastructure.tracking.mlflow import MlflowPromptRegistry

URI = "http://localhost:5000"


def _prompt_version(*, name: str, version: int, tags: dict[str, str]) -> SimpleNamespace:
    """A stand-in for `mlflow.entities.model_registry.PromptVersion`.

    Only the attributes the adapter reads: `.name`, `.version`, `.tags`.
    """
    return SimpleNamespace(name=name, version=version, tags=tags)


@pytest.fixture
def registry(monkeypatch) -> MlflowPromptRegistry:
    import mlflow

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    return MlflowPromptRegistry(URI)


class TestPublish:
    """`publish` maps a `PromptVersion` MLflow hands back onto `PublishedPrompt`."""

    def test_publish_maps_the_returned_version(
        self, registry: MlflowPromptRegistry, monkeypatch
    ):
        """Example: `register_prompt` returns version 2 with the hash tag set."""
        import mlflow

        sent: dict[str, object] = {}

        def fake_register_prompt(*, name, template, commit_message, tags):
            sent.update(name=name, template=template, commit_message=commit_message, tags=tags)
            return _prompt_version(
                name=name, version=2, tags={"dossier.prompt_hash": "35d1a8ef", **tags}
            )

        monkeypatch.setattr(mlflow.genai, "register_prompt", fake_register_prompt)

        published = registry.publish(
            name="incident-audit.verify",
            template="Verify {{claim}}",
            tags={"dossier.pipeline": "incident-audit"},
            commit_message="edited",
        )

        assert sent == {
            "name": "incident-audit.verify",
            "template": "Verify {{claim}}",
            "commit_message": "edited",
            "tags": {"dossier.pipeline": "incident-audit"},
        }
        assert published == PublishedPrompt(
            name="incident-audit.verify",
            version=2,
            prompt_hash="35d1a8ef",
            created=True,
        )

    def test_publish_with_no_hash_tag_returns_an_empty_hash(
        self, registry: MlflowPromptRegistry, monkeypatch
    ):
        """Counter-example: MLflow answers with no `dossier.prompt_hash` tag."""
        import mlflow

        monkeypatch.setattr(
            mlflow.genai,
            "register_prompt",
            lambda **kwargs: _prompt_version(name=kwargs["name"], version=1, tags={}),
        )

        published = registry.publish(name="incident-audit.extract", template="x", tags={})

        assert published.prompt_hash == ""
        assert published.created is True


class TestLatest:
    """`latest` is the one read the port permits, and only that."""

    def test_latest_returns_the_newest_version(
        self, registry: MlflowPromptRegistry, monkeypatch
    ):
        """Example: three versions on the server, out of order."""
        from mlflow import MlflowClient

        versions = [
            _prompt_version(
                name="incident-audit.verify", version=1, tags={"dossier.prompt_hash": "aaa"}
            ),
            _prompt_version(
                name="incident-audit.verify", version=3, tags={"dossier.prompt_hash": "ccc"}
            ),
            _prompt_version(
                name="incident-audit.verify", version=2, tags={"dossier.prompt_hash": "bbb"}
            ),
        ]
        monkeypatch.setattr(MlflowClient, "search_prompt_versions", lambda self, name: versions)

        published = registry.latest("incident-audit.verify")

        assert published == PublishedPrompt(
            name="incident-audit.verify",
            version=3,
            prompt_hash="ccc",
            created=False,
        )

    def test_latest_returns_none_for_a_missing_prompt(
        self, registry: MlflowPromptRegistry, monkeypatch
    ):
        """Counter-example: no such prompt has ever been published.

        MLflow raises `MlflowException(RESOURCE_DOES_NOT_EXIST)` from
        `search_prompt_versions` in that case -- confirmed against the
        installed MLflow against a local sqlite-backed registry, so the
        replacement here raises the same shape rather than an invented one.
        """
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException
        from mlflow.protos.databricks_pb2 import RESOURCE_DOES_NOT_EXIST

        def missing(self, name):
            raise MlflowException(
                f"Prompt with name={name} not found", error_code=RESOURCE_DOES_NOT_EXIST
            )

        monkeypatch.setattr(MlflowClient, "search_prompt_versions", missing)

        assert registry.latest("does-not-exist") is None

    def test_latest_reraises_an_unrelated_mlflow_error(
        self, registry: MlflowPromptRegistry, monkeypatch
    ):
        """Counter-example: some other server failure -- not this method's to hide."""
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException

        def broken(self, name):
            raise MlflowException("the server is unwell")  # defaults to INTERNAL_ERROR

        monkeypatch.setattr(MlflowClient, "search_prompt_versions", broken)

        with pytest.raises(MlflowException):
            registry.latest("incident-audit.verify")
