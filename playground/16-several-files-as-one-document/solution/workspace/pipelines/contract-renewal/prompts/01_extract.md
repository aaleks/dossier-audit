Extract the requested fields from the contract below. A contract may be several
files -- a master agreement and its amendments -- each wrapped in a tag naming
its key. A later amendment overrides the clause it amends.

Every non-null value must carry the key of the file the value came from and the
exact sentence it came from. If a field is not stated in any file, return it as
null with a reason. Do not infer, and do not guess.

<contract>{{documents}}</contract>
