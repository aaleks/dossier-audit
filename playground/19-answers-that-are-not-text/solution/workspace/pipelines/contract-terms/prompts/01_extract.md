Extract the requested fields from the contract below.

- auto_renew: true if the contract renews automatically, false if it says it
  does not. If it says neither, return null with a reason: saying nothing is
  not saying no.
- notice_period: the notice either party must give, as a whole number and a
  unit, such as "90 days" or "3 months", as the contract states it. Do not
  convert months into days.
- sites: every site the contract names, one record per site, each citing the
  sentence that names it. Answer every other field once.

Every non-null value must carry the document's key and the exact sentence it
came from. If a field is not stated, return it as null with a reason. Do not
infer, and do not guess.

<contract>{{documents}}</contract>
