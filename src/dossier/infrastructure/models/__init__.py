"""Model clients: the only package besides connectors that may reach the network (R0.9).

A provider is a package declaring a `dossier.models` entry point (spec 009), the
same way connectors and converters register. The core learns which providers
exist from the group and from nowhere else.
"""
