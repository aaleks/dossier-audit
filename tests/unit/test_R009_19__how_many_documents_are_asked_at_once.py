"""R9.19 — `dossier run` asks a model about at most `N` of a step's documents at
once, and nothing it writes depends on `N`.

How `N` is decided, without a run: `concurrency` reads the flag, else the
environment `.env` fills, else 1, and refuses anything that is not a whole
number of at least 1 by naming where it came from. A decision, so it is in
`domain/` with the environment handed in (CLAUDE.md, "Default to domain/").
"""

from __future__ import annotations

import pytest

from dossier.domain.concurrency import concurrency


class TestHowManyDocumentsAreAskedAtOnce:
    """R9.19 — where `N` comes from, and what is refused."""

    def test_the_flag_says_how_many(self):
        """Row 1: the one with `--concurrency 3`."""
        assert concurrency({}, flag="3") == 3

    def test_the_machine_says_how_many(self):
        """Row 3: the one with `DOSSIER_CONCURRENCY=2` and no flag."""
        assert concurrency({"DOSSIER_CONCURRENCY": "2"}) == 2

    def test_the_command_line_wins_over_the_machine(self):
        """Row 4: the one with both: what is said on the command line wins."""
        assert concurrency({"DOSSIER_CONCURRENCY": "2"}, flag="3") == 3

    def test_unset_is_one(self):
        """Row 5: the one with neither set."""
        assert concurrency({}) == 1

    def test_set_and_empty_is_unset(self):
        """Row 5's boundary: `.env.example` ships the variable blank."""
        assert concurrency({"DOSSIER_CONCURRENCY": ""}) == 1

    @pytest.mark.parametrize("value", ["0", "-1", "four", "2.5", " 3", "+3", "", "٣"])
    def test_a_flag_that_is_not_a_count_is_refused_by_name(self, value: str):
        """Row 7, a counter-example: a flag given, and not a whole number of at least 1.

        An empty flag is a value someone typed, not an unset one. A digit
        from another script is a digit to `str.isdigit` and not to a person
        reading `ps`, so it is refused rather than read as 3.
        """
        with pytest.raises(ValueError) as refused:
            concurrency({}, flag=value)

        assert str(refused.value) == (
            f"--concurrency is {value!r}; it takes a whole number of at least 1."
        )

    @pytest.mark.parametrize("value", ["0", "2.5", "many"])
    def test_a_setting_that_is_not_a_count_is_refused_by_name(self, value: str):
        """Row 7, a counter-example: the one in `.env`, named as the variable."""
        with pytest.raises(ValueError) as refused:
            concurrency({"DOSSIER_CONCURRENCY": value})

        assert str(refused.value) == (
            f"DOSSIER_CONCURRENCY is {value!r}; it takes a whole number of at least 1."
        )

    def test_a_refused_setting_is_refused_even_under_a_flag(self):
        """Row 7's boundary: the flag wins, so a setting it overrides is not read."""
        assert concurrency({"DOSSIER_CONCURRENCY": "many"}, flag="2") == 2

    def test_a_large_count_is_not_capped(self):
        """No ceiling: `dossier` does not know a provider's limit."""
        assert concurrency({}, flag="64") == 64
