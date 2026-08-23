"""Use cases: sync, convert, run, plan, eval.

Orchestrates domain decisions over the protocols in `dossier.domain.ports`.
Takes the connector, the store and the model client as arguments; never
constructs one. That is what lets every use case run against a fake.
"""
