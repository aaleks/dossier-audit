# 18 · Solution

**Read this before you trust a line of it.** Every block below is marked, as
exercises 11's and 15's are:

| Mark | Means |
|---|---|
| **[run]** | Run against this repository and the three live sites. The output is what it produced. |
| **[derived]** | Worked out from the code or the spec, not printed by a command. |
| **[shape]** | What to expect, and what to check. Not a transcript. |

The tasks were run in order, in one pass, on 2026-09-28, at the commit of `main`
that made `render:` part of what a web fetch asks (#529). They were run on
Windows, so `$L` was the worktree's `.venv/Scripts/python.exe`, and a timing is
this machine's.

What will differ in yours:

- **Markers and snapshot addresses.** uv's documentation is rebuilt often, and
  every page's `<lastmod>` is the build date. A page edited since has other
  bytes, so another address.
- **Times.** The watermarks, and every `time`.
- **The quotes site's drawn bytes**, if its scripts or styles change.

---

## Task 1 — a sitemap, and what a second sync costs

**[run]**

```
$ dossier sync site-audit
uv-projects  0 known · 0 changed · 10 new -> 10 fetched
ledger updated · 10 new snapshots · 0 tombstoned

$ $L ledger
uv-projects  build/index                        2026-09-25                 text/html  active
uv-projects  config/index                       2026-09-25                 text/html  active
uv-projects  dependencies/index                 2026-09-25                 text/html  active
uv-projects  export/index                       2026-09-25                 text/html  active
uv-projects  index                              2026-09-25                 text/html  active
uv-projects  init/index                         2026-09-25                 text/html  active
uv-projects  layout/index                       2026-09-25                 text/html  active
uv-projects  run/index                          2026-09-25                 text/html  active
uv-projects  sync/index                         2026-09-25                 text/html  active
uv-projects  workspaces/index                   2026-09-25                 text/html  active

$ dossier sync site-audit
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
```

The first sync took under five seconds.

**[derived]**

- **The keys.** MkDocs writes every page as a directory, `…/projects/build/`,
  and a key is also a file name under `runs/`, which `build/` is not. So a
  directory's key has `index` appended (R1.30). `url`'s own page is the
  directory itself, `index`.
- **The markers.** Every page carries the date the site was built, so every
  page is fetched again after every rebuild, whether it changed or not. That is
  over-fetching, which is always allowed (R1.4). What a marker must never do is
  stay put while a page changes.
- **The second sync** asked for two things: `robots.txt`, answered `404` (allow
  everything, R1.33), and the sitemap. No `<lastmod>` had moved, so no page was
  fetched (R2.1).

## Task 2 — what was held, and what a stage will read

**[run]**

```
$ dossier convert site-audit
uv-projects  10 held · 10 converted · 0 cached
cache updated · 10 converted · 0 cached

$ wc -c $P index.md
62089 .dossier/snapshots/9b/c3/9bc320ee66b1f877b0175c42f94842a61317c63429648e10886125f9cfa73fc6
  811 index.md

$ grep -c "<nav" $P
18
$ grep -o "<main[^>]*>" $P
<main class="md-main" data-md-component="main">

$ head -8 index.md
# [Projects](#projects)

Projects help manage Python code spanning multiple files.

Tip

Looking for an introduction to creating a project with uv? See the [projects guide](../../guides/projects/) first.
```

`Skip to content`, `Initializing search` and the footer are in `$P` and not in
the note, which ends with `April 29, 2026` and `Back to top`.

**[derived]** The page declares one `<main>`, so the note is that element, less
the `<nav>`s inside it: MkDocs Material puts both sidebars there (R8.33). The
header, the tabs and the footer lie outside it. Nothing is chosen by class name
or by how much text a block holds. A page with no `<main>` is written whole,
which is how exercise 3's `PLAY-4001` keeps its breadcrumb (R8.21 row 1). The
revision date and `Back to top` are inside `<main>`: the page's author put them
there, and R8.33 takes the author's word for it.

## Task 3 — a site with no sitemap

**[run]**

```
$ dossier sync site-audit          # python-about, with no crawl:
python-about  0 known · 0 changed · 0 new -> 0 fetched
python-about: listing failed: GET https://www.python.org/sitemap.xml answered 404 Not Found; a web source is listed from its sitemap, and nothing is tombstoned without one (R1.29)
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
1 source(s) could not be listed: python-about
exit 1

$ dossier sync site-audit          # crawl: 5
python-about  0 known · 0 changed · 0 new -> 0 fetched
python-about: listing failed: the crawl has asked 5 URLs, as many as `crawl:` allows, and https://www.python.org/about/legal/ is still to ask. A crawl that stops short would tombstone every page it did not reach, so nothing is listed; raise `crawl:` to list this source (R1.38)
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
1 source(s) could not be listed: python-about
exit 1

$ time dossier sync site-audit     # crawl: 20, delay: 0.5
python-about  0 known · 0 changed · 7 new -> 7 fetched
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
ledger updated · 7 new snapshots · 0 tombstoned
real	0m5.710s

$ $L ledger python-about
python-about apps/index                         -                          text/html  active
python-about gettingstarted/index               -                          text/html  active
python-about help/index                         -                          text/html  active
python-about index                              -                          text/html  active
python-about legal/index                        -                          text/html  active
python-about quotes/index                       -                          text/html  active
python-about website/index                      -                          text/html  active

$ dossier sync site-audit
python-about  7 known · 0 changed · 0 new -> 7 fetched
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
ledger updated · 0 new snapshots · 0 tombstoned
```

**[derived]**

- **Why not an empty listing.** A web listing is complete, and a page gone from
  it is tombstoned (R1.11, R2.7). An empty listing from an unreadable sitemap
  would have tombstoned everything the source held. So it fails instead, and
  R2.27 keeps the failure to its own source.
- **Why not five pages.** The same reason. Listing the five pages it read would
  have tombstoned the other two, and every page a crawl never reached. The next
  sync would have listed a different five, or the same five, and the rest would
  never be held (R1.38).
- **The seven fetches that asked nothing.** The crawl downloaded every page to
  find its links, and kept the bytes. `fetch` hands those back (R1.37 row 2). A
  crawled page has no marker, so each is compared by its bytes, and none had
  changed (R2.2).
- **No default for `crawl:`.** How many pages a site has is its reader's to
  say. A crawl that stopped where a default guessed would fail or, worse, be
  mistaken for the whole site (R1.39).
- **The timing.** Eight requests to python.org (`robots.txt` and seven pages),
  seven gaps of at least half a second: about 3.5 seconds of waiting.

## Task 4 — a page drawn by its script

**[run]** As sent:

```
$ dossier sync site-audit
python-about  7 known · 0 changed · 0 new -> 7 fetched
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
quotes  0 known · 0 changed · 11 new -> 11 fetched
ledger updated · 10 new snapshots · 0 tombstoned

$ dossier convert site-audit
python-about  7 held · 7 converted · 0 cached
uv-projects  10 held · 0 converted · 10 cached
quotes  11 held · 10 converted · 1 cached
cache updated · 17 converted · 11 cached

$ $L note quotes/index
# [Quotes to Scrape](/)

[Login](/login)




- [Next →](/js/page/2/)

Quotes by: [GoodReads.com](https://www.goodreads.com/quotes)

Made with ❤ by [Zyte](https://www.zyte.com)

$ grep -c "Albert Einstein" $($L payload quotes/index)
3
```

Eleven pages and ten snapshots: `index` and `page/1/index` are the same bytes,
held once (R0.2). `Albert Einstein` is in a `<script>`, in `var data = [...]`,
which `html-markdown` takes out, because a reader never sees it (R8.21).

**[run]** Drawn, with `render: browser`:

```
$ dossier sync site-audit
python-about  7 known · 0 changed · 0 new -> 7 fetched
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
quotes  11 known · 11 changed · 0 new -> 11 fetched
      index  a9067d4438044d45a1a895ed6939df4fa4d0487e17b82053dd694ad425466074 -> 966928afef0c332f261a2a699241a53dcc049b803b1cc12ff8b80a2826a59ed7
      page/1/index  a9067d4438044d45a1a895ed6939df4fa4d0487e17b82053dd694ad425466074 -> 966928afef0c332f261a2a699241a53dcc049b803b1cc12ff8b80a2826a59ed7
      page/10/index  9d55598d… -> 6ac119ea…
      […eight more]
ledger updated · 10 new snapshots · 0 tombstoned
real	0m28.380s

$ $L note quotes/index | head -8
# [Quotes to Scrape](/)

[Login](/login)

“The world as we have created it is a process of our thinking. It cannot be changed without changing our thinking.”by Albert Einstein

Tags: change deep-thoughts thinking world

$ head -c 3 $($L payload quotes/index) | od -An -tx1
 ef bb bf

$ dossier sync site-audit
python-about  7 known · 0 changed · 0 new -> 7 fetched
uv-projects  10 known · 0 changed · 0 new -> 0 fetched
quotes  11 known · 0 changed · 0 new -> 11 fetched
ledger updated · 0 new snapshots · 0 tombstoned
```

**[run]** Who asked for what, while the crawl drew its eleven pages. This came
from a copy of the connector's browser that logged each decision; `dossier`
prints none of it:

```
document   GET  https://quotes.toscrape.com/js/                           answered by dossier
stylesheet GET  https://quotes.toscrape.com/static/bootstrap.min.css      answered by dossier
stylesheet GET  https://quotes.toscrape.com/static/main.css               answered by dossier
script     GET  https://quotes.toscrape.com/static/jquery.js              answered by dossier
stylesheet GET  https://fonts.googleapis.com/css?family=Raleway:400,700   send
font       GET  https://fonts.gstatic.com/s/raleway/v37/…ttf              refuse
font       GET  https://fonts.gstatic.com/s/raleway/v37/…ttf              refuse
document   GET  https://quotes.toscrape.com/js/page/2/                    answered by dossier
[…]
77 requests in all
```

**[derived]**

- **Who asked.** Each page was asked for once, by `dossier`, and the browser was
  handed the answer (R1.40 row 2). The site's own stylesheets and script were
  asked through the same path as every page (`robots.txt`, `delay:`, `429`),
  and asked once for all eleven pages (R1.41 row 5). Google Fonts' stylesheet
  is another host's, so the browser sent it itself (row 9). The fonts it named
  were refused, as an image would be (row 1). A `POST` is refused whatever it
  is for, because a connector never writes (R1.1, row 8).
- **Why a byte-order mark.** A drawn page still carries the `<meta charset>`
  the site wrote. Chromium reads a page by its `Content-Type` header when that
  disagrees with the `<meta>`, so the page may have been read in a charset it
  does not declare. Held in UTF-8 behind a mark, which a browser and R8.32 both
  read first, it is read back as it was drawn (R1.40).
- **Why eleven changed.** A crawled page has no marker, and is fetched every
  sync anyway (R1.31, R1.37). So the new bytes were seen without any help,
  which is what hid task 5's problem.
- **Why the third sync wrote nothing.** This site's scripts write the same
  quotes on every load: nothing in them reads the clock or draws a random id.
  A site whose scripts do would store a new snapshot every sync (R2.2).

## Task 5 — drawing a source that is already held

**[run]**

```
$ dossier sync site-audit          # render: browser added to uv-projects
uv-projects  10 known · 10 changed · 0 new -> 10 fetched
      index  9bc320ee66b1f877b0175c42f94842a61317c63429648e10886125f9cfa73fc6 -> 0ead4c89ec771912be4961f4eefddd2b73555efe6335a784e859010b54bdc066
      […nine more]
real	0m50.220s

$ dossier sync site-audit
uv-projects  10 known · 0 changed · 0 new -> 0 fetched

$ wc -c index.md drawn.md          # the notes of uv-projects/index, as sent and drawn
 811 index.md
1271 drawn.md

$ dossier sync site-audit          # render: taken away
uv-projects  10 known · 10 changed · 0 new -> 10 fetched
```

The drawn note differs from task 2's only in its links:
`[projects guide](../../guides/projects/)` became
`[projects guide](https://docs.astral.sh/uv/guides/projects/)`, and every
heading's anchor became absolute.

**[derived]** `render` is part of what a web fetch asks, and so of the source
configuration hash. A change to it fetches every item once, as R2.26 does for
Jira's `expand` (R1.40 row 8). Before row 8, the sync above fetched nothing: no
`<lastmod>` had moved, and all ten pages stayed held as sent. Task 4 hid this,
because a crawled page is fetched on every sync whatever its source says.
Taking `render:` away is the same change in the other direction. It fetched ten
pages and, in this pass, wrote one new snapshot. The other nine pages' bytes as
sent were still in the store from task 1, and a snapshot is addressed by its
bytes (R0.2). One page's bytes had changed since task 1. Drawn, uv took 50
seconds for ten pages, against under five as sent.
