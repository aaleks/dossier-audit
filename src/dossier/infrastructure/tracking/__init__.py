"""Sending a command's record to MLflow (spec 010).

One of the four packages left of the hash boundary (R0.19). It sends records.
What it hands back to the rest of `dossier` is only what specs 012 to 015
fence, each through a port of its own: what a registry says about what it
published or found (`DatasetRegistry`, `VersionRegistry`, `PromptRegistry`),
and reviewers' verdicts, for `dossier review pull` alone (`ReviewSource`,
R15.5). What else it reads -- a health check, a token, whether the server holds
a trace -- stays inside it but for a count of what was lost (R10.18, R10.19,
R10.24). The `Tracker` port has no method that returns anything read from the
server, so nothing MLflow holds can enter a key, a manifest or a score through
it.
"""
