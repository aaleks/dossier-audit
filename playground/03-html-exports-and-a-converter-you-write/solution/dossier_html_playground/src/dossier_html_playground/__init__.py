"""Two converters for formats `dossier` recognises and does not read.

`text/html` and `text/csv` are both in `MEDIA_TYPES`, so a snapshot of either
gets a real media type in the ledger -- and nothing installed claims either pair,
so `dossier convert` stops the run and names them (R8.5). That is the gap this
package fills, and filling it is an installation rather than a patch (R8.7).
"""
