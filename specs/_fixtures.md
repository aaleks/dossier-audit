# Canonical example values

Every example table in `specs/` draws from this set. One vocabulary across seven
specs means an example row transcribes straight into `tests/fixtures/` without a
translation step, and two rules describing the same item are visibly about the
same item.

Do not invent a new incident key for a new example. Add to this file instead.

## Documents

| Key | Source | Kind | Notes |
|---|---|---|---|
| `INC-4821` | `incidents-jira` | issue | The worked example throughout. Loss of CHF 48'200 on page 3. Root cause not stated. |
| `INC-4822` | `incidents-jira` | issue | Changed since last sync. Re-fetched. |
| `INC-4901` | `incidents-jira` | issue | New since last sync. |
| `OPS-114` | `procedures-confluence` | page | Reference material, PDF export, `remote_version` `v37`. |
| `audit-note.pdf` | `incidents-manual` | file | Folder source. No `remote_version`. |

## Hashes

Eight hex characters throughout. They are labels, not real digests, and are used
consistently so a reader can follow one artifact across specs.

| Hash | Belongs to |
|---|---|
| `a3f9c1e2` | `INC-4821` snapshot; also its converted markdown |
| `77c1b40a` | `INC-4822` snapshot, and `extract/INC-4821.json` |
| `0e52dd18` | `INC-4901` snapshot, and `prompts/02_verify.md` |
| `b81f0c6d` | `OPS-114` snapshot, and `schemas/incident.json` |
| `c4a70b93` | `audit-note.pdf` snapshot |
| `9f21c0a4` | the `verify` cache key for `INC-4821` |

## Times

| Value | Meaning |
|---|---|
| `2026-08-06T09:00:00Z` | `last_sync_at` for `incidents-jira` |
| `2026-08-05T09:00:00Z` | the same, minus the default 24h overlap |
| `2026-07-30T09:14:00Z` | `INC-4821` remote version marker |
| `2026-08-05T16:02:00Z` | `INC-4822` remote version marker |
| `2026-08-06T14:22:03Z-4f1a` | the run id used in provenance examples |

## Configuration

| Value | Meaning |
|---|---|
| `anthropic:claude-sonnet-4-5-20250929` | the pinned model identifier |
| `anthropic:claude-sonnet-4-5` | a floating alias — rejected at load time (R0.6) |
| `incident-audit` | the pipeline name |
| `extract` → `verify` → `report` | the three steps |

## Fields on `INC-4821`

| Field | Gold value | Notes |
|---|---|---|
| `loss_amount` | `48200.00` CHF | span `total exposure CHF 48'200`, page 3 |
| `resolution_date` | `2026-07-28` | |
| `severity` | `major` | enum |
| `root_cause` | `null`, reason `not stated in document` | the abstention example |
| `affected_systems` | `["payments-api", "ledger-batch"]` | the field that regressed in the deck's comparison table |
