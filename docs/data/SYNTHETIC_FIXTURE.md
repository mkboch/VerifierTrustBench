# `synthetic_demo_cells.json` — what it is, and the schema

## This file is not evidence

Every value in `synthetic_demo_cells.json` was produced by a random number generator in
`tools/make_synthetic_demo.py`. **No model was run to make it. No manuscript was examined.
Nothing in it is a measurement.** It exists so that the analysis code shipped in this
repository can be demonstrated and tested without publishing any experimental outcome.

Do not cite it. Do not compare numbers computed from it with the published paper. The
study's measured results are reported in the manuscript; see the manuscript's data and code
availability statement for how to request the controlled research dataset.

The file announces itself: `"synthetic": true`, a `warning` string, and systems named
`Demo system A` … `E`, which correspond to nothing. `scripts/audit_public_release.py`
refuses to publish a data file under `docs/data/` that is not marked synthetic, and
`tests/test_synthetic_fixture.py` fails the build if those markers are weakened.

## Regenerating it

```bash
python tools/make_synthetic_demo.py          # deterministic, seed 1104
python tools/update_manifest.py              # refresh docs/data/SHA256SUMS.txt
```

The generator's parameters are invented, and are chosen to make the demonstration show the
*shapes* a reader should learn to look for — a rung whose sensitivity and false alarms rise
together, and one whose does not — rather than to resemble any particular system.

## Using your own data instead

The playground's "A cell table from my own computer" option reads a file of this schema in
your browser. It is never uploaded; the site has no server to upload it to.

If you have run the pipeline on your own manuscripts and models,
`tools/build_fair_scoring_public.py` converts your own frozen records into this shape.

## Schema

A single JSON object.

| key | type | meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `synthetic` | bool | `true` for this fixture. Your own file should set `false`. |
| `systems` | list | `{id, label, proprietary}` — the systems compared |
| `rungs` | list | `{id, record_key, label, exposure, response_interface}`; `id` must be `blind`, `category`, `relation`, `binary` |
| `fields` | list | the column names, in the order the `cells` rows use |
| `cells` | list of lists | one row per `(system, rung, relation)` |
| `n_clusters`, `n_relations` | int | descriptive |

### Columns of a `cells` row

| field | type | meaning |
|---|---|---|
| `system` | str | must match a `systems[].id` |
| `rung` | str | one of the four rung ids |
| `cluster` | str | the resampling unit — one manuscript. Relations sharing a cluster are treated as correlated. |
| `relation` | str | the relation under test |
| `family`, `domain` | str | descriptive strata |
| `e0_scoreable` | 0/1 | the response in the perturbed state was schema-valid and scoreable |
| `e1_scoreable` | 0/1 | the same, in the as-published state |
| `e0_hit` | 0/1/null | the injected defect was detected. `null` when not scoreable. |
| `e1_false_alarm` | 0/1/null | the **same relation** was flagged when it was sound. `null` when not scoreable. |
| `e0_prov_gated` | 0/1/null | verdict rung only: a correct E0 verdict whose cited evidence supports the tested relation |

A cell enters a contrast only when **both** rungs are scoreable in **both** states.

Keep every value a short label, a `0`/`1`, or `null`. The release audit rejects a data file
containing long strings, because that is what a leaked finding or rationale would look like.
