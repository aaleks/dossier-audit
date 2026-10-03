# 25 · Solution

Run on 2026-10-03 against the stub, with `presidio-analyzer` 2.2.364, spaCy
3.8.16 and the four `lg` models at 3.8.0. Output is trimmed to what each task
asks about. Run ids and hashes will differ on your machine.

A small helper reads the call log: for each call, it prints the document and
how many of the seven values its prompt carried. Save it as `count.py`:

```python
import json
canaries = ["Erika Mustermann", "Hans Muster", "erika.mustermann@example.ch",
            "+41 44 555 01 23", "CH93 0076 2011 6238 5295 7", "756.1234.5678.97",
            "CIF 0042-118733"]
for line in open("/tmp/dossier25-calls.jsonl", encoding="utf-8"):
    call = json.loads(line)
    print(call["documents"], sum(value in call["prompt"] for value in canaries), "of 7")
```

---

## Task 1 — what the model was sent

```console
$ dossier sync incident-audit
incidents  0 known · 0 changed · 4 new -> 4 fetched
$ dossier run incident-audit
  extract: 4 document(s) · 0 from cache · 0 failed
$ python count.py
['PLAY-6001.md'] 7 of 7
['PLAY-6002.md'] 7 of 7
['PLAY-6003.md'] 7 of 7
['PLAY-6004.md'] 7 of 7
```

Every call carried every value: the name, the e-mail, the phone, the IBAN, the
AHV number and the client number. That is what any model, or any gateway in
front of one, would have received and could have logged.

## Task 2 — declare masking

```console
$ dossier run incident-audit
  extract: 4 document(s) · 0 from cache · 0 failed
$ python count.py
['PLAY-6001.md'] 0 of 7
['PLAY-6002.md'] 0 of 7
['PLAY-6003.md'] 0 of 7
['PLAY-6004.md'] 0 of 7
```

1. None. Each prompt carries `[PERSON_1]`, `[PERSON_2]`, `[EMAIL_ADDRESS_1]`,
   `[PHONE_NUMBER_1]`, `[IBAN_CODE_1]`, `[CH_AHV_1]` and `[CLIENT_NUMBER_1]`
   where the values were. The root cause still grounds: the stub quotes the
   root-cause sentence, which names no client, so the quote is found in the
   masked text the model was shown (R6.4).
2. By number, in order of first appearance within the document. `PLAY-6001`
   names `Hans Muster` first, so he is `[PERSON_1]`. `PLAY-6002` names
   `Erika Mustermann` first, so she is `[PERSON_1]` there: numbering starts
   again in each document (R21.2). With `[PERSON]` for both, "[PERSON]
   confirmed what [PERSON] reported" would not say whether one person
   confirmed their own report.
3. The German note's record:

   ```json
   {
     "kind": "mask",
     "language": "de",
     "masked": {"CH_AHV": 1, "CLIENT_NUMBER": 1, "EMAIL_ADDRESS": 1,
                "IBAN_CODE": 1, "PERSON": 2, "PHONE_NUMBER": 1},
     "masker_id": "presidio",
     "masker_version": "1.0.0",
     "masking_version": "1",
     "text": "ea9354ca…"
   }
   ```

   Read in `de`, by a vote over each language's function words (R21.9). It
   counts the values masked by type, and it names the converted text by its
   hash. It never writes a value down. The cache entry beside it holds the
   masked text, with nothing to undo it.
4. Zero. The masked view is cached under a key made of the converted text,
   the masker and its version, and the declaration (R21.5), so the run shows
   `4 from cache` and the masker is never asked. Editing a prompt re-runs the
   step and still masks nothing again.

## Task 3 — what is refused, not sent

```console
$ dossier run incident-audit          # score_threshold deleted
cid.yaml: score_threshold -- Field required
$ echo $? ; wc -l < /tmp/dossier25-calls.jsonl
2
0
```

```console
$ dossier run incident-audit          # the step reads documents@page_images
pipeline.yaml: masking is declared, and step 'extract' reads page_images. A picture
of a page cannot be masked, so a masked pipeline never shows a model one (R21.7).
$ echo $? ; wc -l < /tmp/dossier25-calls.jsonl
2
0
```

Both are refused before any call (R21.7). A threshold is required because it
decides which recognisers count, and that is the author's choice. A picture of
a page carries the name in its pixels, where no masker reaches.

If you changed only `input:` and not the prompt, you met R3.6 first: a
declared input that no placeholder uses is refused before masking is
considered.

## Task 4 — a file named after the client

```console
$ dossier run incident-audit
  incidents: Erika-Mustermann-complaint.md could not be masked: its key names client
  data, and a key is shown to the model; rename it at the source
  extract: 4 document(s) · 4 from cache · 0 failed
$ echo $?
1
$ grep -c Erika-Mustermann /tmp/dossier25-calls.jsonl
0
```

A document's key is shown to the model in every `<document key="...">`
(R3.13). A file named after the client would carry the name past its own
masked text, so the key is checked as well, and the document fails alone
(R21.8). The key is read with its `-`, `_` and `.` as spaces first. A
named-entity model reads `Erika-Mustermann-complaint.md` as one word and
finds no person in it. This was found by running this task, and fixed in
#731.

## Task 5 — what the threshold decides

At `score_threshold: 0.5`, `PLAY-6005`'s prompt holds the number as written:

```
Die Kundin bittet um Rückruf unter +41 44 555 01 23, sobald die Zahlung freigegeben ist.
```

At `0.4`:

```
Die Kundin bittet um Rückruf unter [PHONE_NUMBER_1], sobald die Zahlung freigegeben ist.
```

Presidio scores a phone number 0.4 on its own, and 0.75 beside a word that
says it is one. `PLAY-6002` writes `Telefon` beside it, which is one of the
masker's context words. `Rückruf` is not one of them. So the threshold is a
choice of which recognisers count, and `dossier` ships no number for it. A
lower threshold masks more, and also more that is not client data.

## Task 6 — what the allow-list is for

Without `allow:`, the German note's prompt reads:

```
[PERSON_2] aus dem Filialnetz bestätigte, dass der [PERSON_3] consumer lag auf
```

`de_core_news_lg` takes `Kafka` for a person. Masked, the model can no longer
tell that the incident is about a message queue's consumer lag. That is a
false positive, and it costs signal rather than privacy. The allow-list names
the values that are never masked, such as systems, vendors and sites, and
keeps them.

## Task 7 — what was promised

Masking guarantees that every value the masker *detects* is replaced in
everything a masked pipeline shows a model, including `reference` and an
eval's judge, and that anything it cannot mask is refused rather than sent.
It does not guarantee that the masker detects every client value.
Named-entity recognition is statistical: here, the German model found
`Hans Muster` only once line breaks were read as spaces. So recall on real
incidents is measured on a labelled sample, against a threshold someone
agrees to (R21.14), and not promised.

Not shown here:
- the index and `dossier search`, a later part of spec 021;
- a scanned page, which is refused rather than masked;
- calibration over gold values that name a client.
