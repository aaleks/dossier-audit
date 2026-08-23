"""Test doubles.

`dossier` has no LangChain, so there is no `FakeListChatModel` to borrow. The
fake below implements the same shape the production code will take a model
client in as -- and, critically, it **counts calls**.

Counting is not a nicety. R2.5, R4.6, R5.5 and R5.7 are all claims about how many
calls happened, not about what came back. A fake that only returns canned text
cannot prove any of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class FakeModelClientError(AssertionError):
    """Raised when a test asks the fake for more responses than it was given.

    An AssertionError rather than a plain exception: running out of scripted
    responses means the code under test made a call the test did not expect,
    which is a finding, not an infrastructure problem.
    """


@dataclass
class FakeModelClient:
    """A model client that returns canned responses and remembers every call.

    Responses are consumed in order. `model_id` is recorded on every call so a
    test can assert which pin was used without reaching into production code.
    """

    responses: list[str] = field(default_factory=list)
    model_id: str = "anthropic:claude-sonnet-4-5-20250929"
    calls: list[dict[str, object]] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        self.calls.append({"prompt": prompt, "schema": schema, "model_id": self.model_id})
        if not self.responses:
            raise FakeModelClientError(
                f"call {self.call_count} was made with no scripted response left. "
                "Either the code under test called the model more often than the "
                "test expected, or the script is short."
            )
        return self.responses.pop(0)


class NoModelClient:
    """A client that fails on any call at all.

    For the rules that say *zero* calls -- `--plan` (R4.6), a full cache hit
    (R5.5), config loading (R3.8). Asserting `call_count == 0` proves the same
    thing, but this fails at the call site, which is where the answer is.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        raise FakeModelClientError(
            "a model call was made where the rule under test permits none"
        )
