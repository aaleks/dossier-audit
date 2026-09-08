"""Converters: snapshot bytes in, artifact bytes out (spec 008).

Every module here is right of the hash boundary, so none of them may touch the
network on any code path (R0.1), and every one of them must be a pure function of
its input and its declared options (R8.1). Both are checked rather than trusted.
"""
