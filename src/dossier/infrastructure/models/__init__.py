"""Model clients: one of the four packages that may reach the network (R0.19).

The one that asks a model, for an answer or for a vector, and only on a cache
miss. A provider is a package declaring a `dossier.models` entry point (spec
009), the same way connectors and converters register. The core learns which
providers exist from the group and from nowhere else.
"""
