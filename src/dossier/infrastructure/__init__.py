"""Wiring: converters, the snapshot store, the ledger, model clients, tracking.

Wiring, not judgement. A decision that appears here -- a threshold, a precedence
choice, a validity check -- belongs in `dossier.domain`, where it can be tested
without a server. SDK imports go inside functions, not at module scope.
"""
