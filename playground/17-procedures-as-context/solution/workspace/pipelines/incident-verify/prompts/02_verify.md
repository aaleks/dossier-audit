Check the extraction below against the incident it was made from, and fill in
what the procedures say applies to it. Each document is wrapped in a tag naming
its key.

Every non-null value must carry the key of the document it came from and the
exact sentence it came from: the incident for what happened, the procedure for
what was required. Return a field as null with a reason if no document states it.

<incident>{{documents}}</incident>
<extraction>{{extract}}</extraction>
<procedures>{{reference}}</procedures>
