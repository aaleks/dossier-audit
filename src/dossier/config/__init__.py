"""Loading and validating `sources.yaml` and `pipeline.yaml`.

The only package that reads `os.environ`. Loading is a pure function of files on
disk: no network, no model calls (R3.8).
"""
