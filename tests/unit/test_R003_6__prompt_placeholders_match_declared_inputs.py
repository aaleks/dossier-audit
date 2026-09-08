"""R3.6 — prompt placeholders and declared inputs correspond exactly.

Every `{{...}}` in a prompt is a declared input of that step, and every declared
input appears in the prompt. Either mismatch is a load-time error: an unused
input is a silent no-op, and an unfilled placeholder reaches the model as
literal braces.

Both halves fail quietly without this check, which is why it is a rule rather
than a convention. A declared-but-unused input costs a stage key that moves for
a reason nothing can see (R5.2). An undeclared placeholder ships `{{reference}}`
to the model as text, and the answer that comes back looks plausible.

Placeholders are matched against inputs **as declared**, sugar included: a step
writing `input: previous` writes `{{previous}}`. The rule says load-time, and at
load time `previous` has not been expanded -- spec 004 does that later. It also
keeps the prompt correct through an insertion, which is what the sugar is for.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.prompts import check_placeholders, placeholders_in, render


class TestPlaceholdersMatchDeclaredInputs:
    """R3.6 — neither side may carry something the other does not."""

    def test_a_prompt_naming_every_declared_input_is_accepted(self):
        """Example 1: the one where the two sides agree."""
        check_placeholders(
            step="verify",
            declared=["documents", "extract"],
            prompt="<source_document>{{documents}}</source_document>\n"
            "<extraction>{{extract}}</extraction>\n",
        )

    def test_a_declared_input_never_injected_is_an_error(self):
        """Example 2: the one where `extract` is declared and unused.

        The step reads `extract`, so `extract` is in its key and a change to it
        re-runs the stage -- for no reason anybody could find, because the model
        never saw it.
        """
        with pytest.raises(ValueError) as error:
            check_placeholders(
                step="verify",
                declared=["documents", "extract"],
                prompt="<source_document>{{documents}}</source_document>\n",
            )

        message = str(error.value)
        assert "verify" in message
        assert "extract" in message

    def test_an_injected_placeholder_never_declared_is_an_error(self):
        """Example 3: the one where `{{reference}}` would ship as literal braces.

        Nothing fills it, so the model receives the six characters and answers
        anyway. That answer is the failure mode this row exists to prevent.
        """
        with pytest.raises(ValueError) as error:
            check_placeholders(
                step="verify",
                declared=["documents"],
                prompt="<source_document>{{documents}}</source_document>\n"
                "<procedure>{{reference}}</procedure>\n",
            )

        message = str(error.value)
        assert "verify" in message
        assert "reference" in message

    def test_braces_inside_a_fenced_code_block_are_not_placeholders(self):
        """Counter-example (row 4): the one where a prompt shows example code.

        A prompt that teaches the model an output format will contain braces.
        Treating them as inputs would make the most useful prompts unwritable.
        """
        prompt = (
            "<source_document>{{documents}}</source_document>\n"
            "\n"
            "Return JSON shaped like this:\n"
            "\n"
            "```json\n"
            '{{"field": "loss_amount", "value": 48200.00}}\n'
            "```\n"
        )

        check_placeholders(step="extract", declared=["documents"], prompt=prompt)
        assert placeholders_in(prompt) == {"documents"}

    def test_a_tilde_fenced_block_is_also_skipped(self):
        """The one where the fence is `~~~` rather than backticks.

        Both are markdown fences. Handling only one is the kind of gap that is
        found by the one person who writes prompts the other way.
        """
        prompt = "{{documents}}\n~~~\n{{not_an_input}}\n~~~\n"

        assert placeholders_in(prompt) == {"documents"}

    def test_the_sugar_is_matched_as_written(self):
        """The one where `input: previous` wants `{{previous}}`.

        At load time `previous` has not been expanded, so this is the only form
        the check can compare against -- and a prompt written this way keeps
        meaning the right thing when a step is inserted above it (R4.5).
        """
        check_placeholders(
            step="verify", declared=["previous"], prompt="<earlier>{{previous}}</earlier>"
        )

        with pytest.raises(ValueError):
            check_placeholders(
                step="verify", declared=["previous"], prompt="<earlier>{{extract}}</earlier>"
            )

    def test_the_error_says_which_side_is_missing_what(self):
        """The one where the message is enough to act on.

        "placeholders do not match" sends someone to diff two lists by eye. The
        two mismatches have different fixes, so the message names which it is.
        """
        with pytest.raises(ValueError) as declared_unused:
            check_placeholders(step="verify", declared=["documents", "extract"],
                               prompt="{{documents}}")
        with pytest.raises(ValueError) as never_declared:
            check_placeholders(step="verify", declared=["documents"],
                               prompt="{{documents}}{{reference}}")

        assert "declared" in str(declared_unused.value).lower()
        assert str(declared_unused.value) != str(never_declared.value)

    def test_a_placeholder_may_be_repeated(self):
        """The one where an input is injected twice on purpose.

        Correspondence is about which names appear, not how often. A prompt that
        restates the document after a long instruction block is a real technique.
        """
        check_placeholders(
            step="extract",
            declared=["documents"],
            prompt="{{documents}}\n...instructions...\n{{documents}}",
        )

    def test_whitespace_inside_the_braces_is_tolerated(self):
        """The one where someone writes `{{ documents }}`.

        Rejecting it would be technically defensible and would waste an
        afternoon. It is unambiguously the same placeholder.
        """
        assert placeholders_in("{{ documents }}") == {"documents"}


class TestRenderingIsTheOtherHalf:
    """R3.6's rationale only holds if placeholders are actually filled.

    "An unfilled placeholder reaches the model as literal braces" is a statement
    about what filling prevents, so the filling belongs beside the check that
    guards it -- one module, one idea about what a placeholder is.
    """

    def test_each_placeholder_becomes_the_text_of_its_input(self):
        """The one where the prompt the model sees has no braces left."""
        rendered = render(
            "<source_document>{{documents}}</source_document>\n"
            "<extraction>{{extract}}</extraction>",
            {"documents": "Loss of CHF 48'200.", "extract": '{"loss_amount": 48200.0}'},
        )

        assert "{{" not in rendered
        assert "Loss of CHF 48'200." in rendered
        assert "<source_document>" in rendered, "the author's tags are untouched"

    def test_a_repeated_placeholder_is_filled_every_time(self):
        """The one where restating the document after instructions works."""
        rendered = render("{{documents}}|{{documents}}", {"documents": "X"})

        assert rendered == "X|X"

    def test_example_code_in_a_fence_survives_rendering(self):
        """The one that matches the counter-example the checker already honours.

        A fence the checker refuses to read inputs out of must also be a fence
        the renderer refuses to write into. Two different answers about what a
        fence is would corrupt exactly the prompts the check was protecting.
        """
        prompt = '{{documents}}\n```json\n{{"field": "loss_amount"}}\n```\n'

        rendered = render(prompt, {"documents": "the document"})

        assert "the document" in rendered
        assert '{{"field": "loss_amount"}}' in rendered
