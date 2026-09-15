"""R10.1 — tracking is off unless `DOSSIER_MLFLOW_ENABLED` is `true`.

Whether a machine records its runs is per machine, read from the environment or
`.env` (R9.11), never from committed configuration. The decision is pure: it
takes the environment as a mapping, which `dossier.config` supplies, so it reads
nothing itself.

Off is `None` rather than a flag: a caller handed nothing to record with cannot
record, which is the structural half of "0 tracking calls". Counting the calls a
run makes is spec 011's, through the tracker port.
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import TrackingSettings, settings

URI = "http://localhost:5000"


class TestTrackingIsOffUnlessEnabled:
    """R10.1 — tracking is off unless `DOSSIER_MLFLOW_ENABLED` is `true`."""

    def test_enabled_with_a_uri_records_there(self):
        """Example 1: the one switched on, recording to `http://localhost:5000`."""
        found = settings({"DOSSIER_MLFLOW_ENABLED": "true", "DOSSIER_MLFLOW_TRACKING_URI": URI})

        assert found == TrackingSettings(uri=URI)

    def test_neither_variable_set_is_off(self):
        """Example 2: the one where nobody asked for tracking."""
        assert settings({}) is None

    def test_a_value_that_is_neither_true_nor_false_is_refused_naming_both(self):
        """Example 3: the one with `DOSSIER_MLFLOW_ENABLED=ture`.

        Refused rather than read as off: a typo that silently disabled tracking
        would be found only after the run it should have recorded.
        """
        with pytest.raises(ValueError) as error:
            settings({"DOSSIER_MLFLOW_ENABLED": "ture", "DOSSIER_MLFLOW_TRACKING_URI": URI})

        message = str(error.value)
        assert "DOSSIER_MLFLOW_ENABLED" in message
        assert "true" in message and "false" in message

    def test_enabled_with_no_uri_is_refused_naming_the_uri_variable(self):
        """Example 4: the one switched on with nowhere to record to.

        The URI has no default in code; `.env.example` states one where it can
        be read (spec 010).
        """
        with pytest.raises(ValueError) as error:
            settings({"DOSSIER_MLFLOW_ENABLED": "true"})

        assert "DOSSIER_MLFLOW_TRACKING_URI" in str(error.value)

    def test_mlflows_own_variables_do_not_switch_tracking_on(self):
        """Counter-example (row 5): the one with `MLFLOW_TRACKING_URI` left in the shell.

        A shell left over from another project must not switch this one's
        tracking on; only `DOSSIER_` variables are read (R9.11).
        """
        assert settings({"MLFLOW_TRACKING_URI": URI}) is None
