"""Two converters for pairs `dossier` already answers, answering only where named.

`html-markdown` and `text-csv` ship in `dossier` and answer `(text/html,
markdown)` and `(text/csv, markdown)` by default (R8.21, R8.23). This package
claims both pairs again, for a reason of this workspace's own: the wiki's
breadcrumb, and a register someone wants as a table. Two claims on one pair are
refused rather than settled by installation order, so both converters are
opt-in, and a workspace chooses one by naming it under `converters:` in
`sources.yaml` (R8.13). Claiming a pair is an installation, never a patch to
`dossier` (R8.7).
"""
