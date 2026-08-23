"""Pure decisions. The purity boundary.

Imports the standard library and pydantic, and nothing else: no file IO, no
network, no clock, no `os.environ`, no YAML, no SDK. A function here takes what
it needs as an argument.

That is what makes these rules testable with a plain dict in milliseconds, and
it is why mutation testing is scoped to this package alone (mutation.toml).
"""
