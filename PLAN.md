# `zooma-client` — implementation plan

**Status:** plan only, no implementation.
**Date:** 2026-09-24
**Decision inputs:** wrap both v3 map and v2 annotate (modelled separately);
PyPI name `zooma-client`, scope Zooma-only; sync-only core.

---

## 1. Goal

Extract the ZOOMA API logic from the Galaxy tool wrapper
(`RECETOX/galaxytools/tools/zooma/zooma.py`, 387 lines, PR #797) into a
standalone, reusable Python package, and reduce the tool to TSV I/O plus a
result→column mapping.

**Success criteria**

1. The Galaxy tool's command block calls the package; `zooma.py` no longer
   contains any HTTP, batching, retry or response-parsing code.
2. All five existing planemo tests still pass unchanged in their assertions.
3. The package is usable without Galaxy: `python -c "import zooma_client"` in a
   bare venv, against the live API, in ~10 lines.
4. No consumer has to know that `targetOntologies` fails open (§4.1) — the
   library makes that impossible to get wrong.

**Non-goals for v1**

- Name/term resolution (OLS4). Deferred deliberately — see §8.
- Async. Deferred — see §7.
- The `-stream` (SSE) endpoints. Deferred — see §6.
- A conda-forge/bioconda recipe at release time — required *before the tool
  can ship*, tracked as a hard gate in §9, not a code task.

---

## 2. Why this is worth doing

Nothing equivalent exists. Verified 2026-09-23/24:

- Full PyPI index (46 MB name dump) grepped for `zooma` → 4 unrelated hits
  (`zoomai`, `zoomaker`, `zoomascii`, `sphinx-zoomable-images`).
- `zooma`, `zoomapy`, `ebi-zooma`, `pyzooma`, `zooma-client`, `zooma-api` →
  PyPI JSON API 404. `zooma-client` is therefore **available**.
- `bioservices` 1.16.0 has **no** Zooma class
  (`gh search code "Zooma" --repo cokelaer/bioservices` → `[]`).
- Nothing on bioconda/conda-forge.
- The only ZOOMA client library anywhere is Perl: `Atlas/ZoomaClient.pm` in
  `ebi-gene-expression-group/perl-atlas-modules`.

So the package has no upstream to contribute to and no alternative to depend on.
It is also the reusable core the EBI does not ship: the service has **no
published OpenAPI spec** (`/v3/api/openapi`, `/openapi.json`, `/api-docs` all
404), so the only machine-readable contract is the Java DTOs in
`EBISPOT/zooma2/backend/src/main/java/uk/ac/ebi/zooma2/api/v3/dto/`.

---

## 3. Verified API facts

Every row below was checked against the live service on 2026-09-24. This table
is the specification for the client; do not code from the tool's docstrings or
from any pre-2026 example online.

| Endpoint | Status | Note |
|---|---|---|
| `GET /spot/zooma/v3/api/health` | 200 `text/plain` "All systems are operational." | the only real health endpoint |
| `GET /spot/zooma/v3/api/status` | 200 JSON | metrics blob, not health |
| `POST /spot/zooma/v3/api/services/map` | 200 | primary API |
| `GET /spot/zooma/v3/api/ontology-presets` | 200 | 2 presets, see §6 |
| `GET /spot/zooma/v3/api/sources` | 200 | provenance source catalogue |
| `GET /spot/zooma/v3/api/models` | 200 | 4 models, only `llama-embed-nemotron-8b_pca512` has `can_embed:true` |
| `GET /spot/zooma/v2/api/services/annotate?propertyValue=` | 200 JSON | **still alive** |
| `GET /spot/zooma/v2/api/properties`, `/annotations` | **404** | v2 data routes removed |
| any unknown path under `/spot/zooma/` | **200 + SPA HTML** | trap: never trust a 200 |

**Request DTOs** (recovered from validation errors, which enumerate every
accepted field):

```
V3MapRequestDto: returnAll, excludeTermIds, properties, definingOnly,
                 includeOtherOntologies, filter, model, deep, targetOntologies
V3StringToMapDto: textToMap, propertyType          (exactly these two)
V3FilterDto:      preferred, required
```

**Server limits** (from `EBISPOT/zooma2/README.md`, enforce client-side):
`MAX_PROPERTIES=1000`, `MAX_DEEP_PROPERTIES=200`, `MAX_PROPERTY_TEXT_LENGTH=1000`,
`MAX_ANNOTATE_TEXT_LENGTH=50000`, `MAX_REQUEST_BYTES=2097152`.

**Response shape** (v3 map, verified):

```json
{"mappings":[{"propertyType":null,"textToMap":"body mass index",
  "candidates":[{"termId":"EFO_0004995","label":"lean body mass","ontology":"efo",
    "uri":"http://www.ebi.ac.uk/efo/EFO_0004995","confidence":1.0,"datasource":"gwas",
    "mappingProvenance":[{"method":"curated","matchType":"CURATED_EXACT","source":"gwas",
      "model":null,"confidence":null,"input":"...","matchedText":"...",
      "similarity":1.0,"target":"..."}]}]}]}
```

Two structural facts the client must encode:

- Mappings come back **positionally, one per submitted value**, echoed in
  `textToMap`. Match positionally, not by value — value matching merges
  duplicate inputs. (This is exactly the bug fixed in `5981516a`.)
- A mapping may carry an `error` field instead of candidates.

---

## 4. Known API traps → required library behaviour

### 4.1 `targetOntologies` fails open ⚠️ highest-priority correctness issue

`targetOntologies` is **additive, not restrictive**. Verified:

| Request | Candidates | Ontologies returned |
|---|---|---|
| *(no filter)* | 12 | cmo, efo, exo, mesh, ncit, omit, pbpko, snomed |
| `targetOntologies:["hp","mondo"]` | **12** | **unfiltered — identical to no filter** |
| `+ includeOtherOntologies:false` | 3 | hp |
| `targetOntologies:["efo"], includeOtherOntologies:false` | 4 | efo |
| `targetOntologies:["zzzz_nope"], includeOtherOntologies:false` | 0 | *(no fallback)* |

Sending the filter alone returns results the user explicitly excluded, with
plausible-looking output. A pipeline does not error; it is silently wrong.

**Library behaviour:**
- `include_other_ontologies` defaults to `False` whenever `target_ontologies` is
  non-empty.
- After every response, assert returned candidate ontologies ⊆ requested set;
  raise `FilterViolation` otherwise. Cheap, and catches server-side drift.

### 4.2 A 200 response can be the web app

Any unrecognised path under `/spot/zooma/` returns HTTP 200 with SPA HTML.
The tool's commit `5cdde35e` documents this biting on `/v2/health`.

**Library behaviour:** validate `Content-Type` and payload *shape* on every call;
raise `UnexpectedResponseError` on HTML. Never `resp.json()` blindly.

### 4.3 Two `MAX_*` limits interact

`deep=True` lowers the batch ceiling from 1000 to 200. The client must apply
`min(MAX_PROPERTIES, MAX_DEEP_PROPERTIES if deep else ∞)`.

### 4.4 v2 annotate is single-value only

It accepts one `propertyValue` per call and **ignores unknown query params** —
`?ontologies=efo` returned a byte-identical 79 886-byte body. So "batching" in
annotate mode is a retry/skip grouping unit, not a request reduction. The
docstring must say so, or someone will assume it batches requests.

### 4.5 Retry warnings contain the string `error:`

Upstream API messages contain `400 Client Error:`. With Galaxy
`detect_errors="aggressive"` this failed jobs that had recovered — the tool now
uses `exit_code` for exactly this reason. **The library must never write to
stdout/stderr itself** (§7.1); any consumer that greps logs for `error` must be
able to opt out.

---

## 5. What moves out of the tool, and what stays

### Moves to `zooma_client`

| Existing function | Becomes |
|---|---|
| `check_service_health` | `Client.health()` |
| `query_zooma_map` | `Client.map_terms()` |
| `query_zooma_annotate` | `Client.annotate()` |
| `split_batches` + the loop in `process_query_values` | `Client.map_all()` / `annotate_all()` |
| attempt/retry/consecutive-failure logic | `RetryPolicy` (§7.2) |
| `annotation_cache` | value→result dict inside `annotate_all()` |
| `ZoomaServiceError` | `ZoomaError` hierarchy (§7.4) |
| `describe_values` | `zooma_client.util.preview_values` (generic) |
| endpoint URLs, DTO shapes, server limits | module constants |

### Stays in the tool

- `read_query_values` — TSV/header/column-index semantics are Galaxy's.
- `normalize_annotations`, `normalize_map_results`, `get_nested_field`,
  `output_columns` — the flat 8-column table is a presentation choice.

**The flattening must not be frozen into the library.** The current mapping
lies about its vocabulary to preserve a v2-shaped TSV:

```python
"semantic_tags": candidate.get("termId", ""),   # a term id, in a column named semantic_tags
"study_type":    candidate.get("uri", ""),      # a URI, in a column named study_type
"source_type":   candidate.get("ontology", ""),
```

Baking that into the library would make the library's public API wrong for every
future consumer just to keep one tool's header stable. The library returns
`Mapping`/`Annotation` objects; the tool maps them to columns.

**Optional follow-up (separate PR, not this refactor):** rename v3-mode columns
to `term_id` / `term_uri` / `ontology` / `match_method` / `similarity`, which
also exposes `matchType` and `similarity` that are today dropped. That is a
user-visible output change and needs its own decision.

---

## 6. Public API

```
zooma_client/
  __init__.py        # public re-exports, __version__
  client.py          # Client — the only class most users touch
  models.py          # frozen dataclasses mirroring the DTOs
  errors.py          # exception hierarchy
  batching.py        # chunking + limit enforcement
  retry.py           # RetryPolicy, Sink protocol
  endpoints.py       # URL constants, server limits
  py.typed
```

```python
class Client:
    def __init__(
        self,
        *,
        base_url: str = "https://www.ebi.ac.uk/spot/zooma",
        timeout: float = 30.0,
        session: requests.Session | None = None,   # injectable; also the test seam
        retry: RetryPolicy = RetryPolicy(),
        sink: Callable[[str], None] | None = None, # progress; default no-op
    ) -> None: ...

    def health(self) -> bool                                   # raises if down
    def map_all(
        self, values: Sequence[str], *,
        batch_size: int = 10,
        property_type: str | None = None,
        target_ontologies: Sequence[str] = (),
        include_other_ontologies: bool | None = None,   # None→False if filtering
        exclude_term_ids: Sequence[str] = (),
        defining_only: bool = False,
        return_all: bool = False,
        deep: bool = False,
        model: str | None = None,
        on_error: Literal["skip", "raise"] = "skip",
    ) -> Iterator[Mapping]                                   # lazy, per input value

    def annotate(self, value: str) -> list[Annotation]         # v2, single value
    def annotate_all(self, values, *, batch_size=10, on_error="skip") -> Iterator[Annotation]

    def presets(self) -> list[Preset]      # /ontology-presets
    def sources(self) -> list[Source]      # /sources
    def models(self) -> list[Model]        # /models  (name it list_models to avoid clash)
```

Design notes:

- **Iterators, not lists.** Galaxy streams to the writer as batches land; a
  list return would force buffering and lose incremental output. Yields are
  grouped per input value so a skipped value is representable.
- **`on_error` replaces the hard-coded skip policy.** The tool keeps
  `"skip"`; library users who want a hard failure get `"raise"`. The
  *two-consecutive-batch-failure abort* moves into `RetryPolicy` as
  `max_consecutive_failures=2` so the tool's exact behaviour is preserved but
  configurable.
- **v2 and v3 get distinct result types** (`Annotation` vs `Mapping`), never a
  merged "common" shape — they carry genuinely different evidence
  (`provenance.source.name` vs `mappingProvenance[].method/similarity`), and the
  merged shape is what produced the lying column names.
- **Streaming endpoints deferred**: `map-stream` and `annotate-text-stream` are
  SSE. `annotate_text` has no non-stream variant, so annotate-text support is
  blocked on SSE parsing. Not in v1; `parse_sse()` noted as the extension point.
- **`presets()` exists but does not decide ontology scope.** The two live
  presets are `EFO and OBO Foundry` (222 ontologies) and `Just OBO Foundry`
  (221). The Galaxy `ontology_filter` select maps to a *hard-coded* list in the
  tool; only `custom` benefits from `presets()`/`sources()` at runtime.

---

## 7. Cross-cutting design

### 7.1 Logging: a sink, not `logging`

`log_message` prints to **stdout because Galaxy surfaces job stdout**, and
`zooma.xml` asserts on the literal strings
`WARNING: batch 2 failed, retrying once\. Reason: .*`.

If the library called `logging.info()` or wrote to stderr, those assertions
break and the tool's user-visible behaviour changes. Therefore:

- The library **never configures logging** and never writes to a stream itself.
- Progress goes to an injected `sink: Callable[[str], None]`. The tool passes
  `log_message` and keeps byte-identical output.
- Library users pass `logging.getLogger(...).warning` or `print` or nothing.

This keeps the tests green *and* avoids the library dictating a logging config —
the usual reason a small client library gets rejected downstream.

### 7.2 Retry policy — and a live question

The tool's current policy: each batch tried exactly twice, no backoff, no HTTP
status discrimination; a batch that fails twice is skipped; two consecutive
skipped batches abort the job.

`RetryPolicy(max_attempts=2, max_consecutive_failures=2, backoff=...)` preserves
that. But the *absence* of backoff and status-code handling is a real gap: a 503
during a ZOOMA restart is retried immediately, once, and then the values are
lost. Two sub-decisions:

- **(a) Exponential backoff** (`backoff=0.0` default = today's behaviour, but
  the tool opts into e.g. `backoff=1.0, factor=2`). Low risk, clear win for a
  flaky-network research tool.
- **(b) Retry on 5xx/429 but not 4xx.** ⚠️ **This changes the tool's test
  expectations.** `input_overlong.tsv` and `input_two_overlong.tsv` exercise the
  skip/abort paths *precisely because* a >1000-char value is a permanent 400. If
  4xx stops being retryable, the "failed, retrying once" line never appears and
  test 4's `<has_line_matching>` assertion fails.

**Recommendation:** implement (b) correctly in the library (4xx non-retryable)
and, in the tool, drive the retry/skip tests off `on_error="raise"`-free inputs
that fail transiently, or accept that test 4 loses its retry assertion and
re-baseline it explicitly with a comment. **Do not discover this mid-migration**
— it is the single most likely thing to look like a regression while being an
improvement. Flagged for your call; see §11 Q2.

### 7.3 Validation client-side

Raise before any network call when: a value exceeds 1000 chars; a batch exceeds
the applicable limit (§4.3); the request body would exceed 2 MiB. The tool
currently discovers these as server 400s, which costs a round trip and produces
worse messages.

### 7.4 Exceptions

```
ZoomaError                 (base)
├── ServiceUnavailableError   health check failed / repeated failures
├── RequestError              transport-level (wrap requests.RequestException)
├── InvalidRequestError       client-side validation, 4xx
├── UnexpectedResponseError   bad content-type / shape / count mismatch (§4.2)
└── FilterViolation           returned ontologies outside request (§4.1)
```

Preserves the tool's existing `except (ZoomaServiceError, ValueError)` semantics
via multiple inheritance or by catching `ZoomaError`.

### 7.5 No asyncio

**There is currently no concurrency in the tool.** Verified: 0 matches for
`asyncio|aiohttp|tenacity|import logging` across `zooma.py`, `zooma.xml`,
`macros.xml`; and `gh search code "asyncio org:RECETOX path:tools"` → `[]`. So
async is a new feature, not a refactor. Map mode already gets its throughput
from batching many values into one request.

Sync-only, per decision. `session=` injection leaves room to add an async facade
later without breaking the API. Worth revisiting **only** for annotate mode at
scale, where N sequential calls is the one genuinely slow path (§11 Q1).

---

## 8. Name resolution: deliberately deferred

**Claim to examine:** the idea was that this package also hosts "utilities for
name resolution etc." for reuse.

The need is real — v3 returns `termId`/`uri`, and v2 annotate returns
`_links.olslinks` with OLS4 hrefs plus `semanticTag`, so resolving and
validating terms against OLS4 is needed by this tool *and* by pipelines like
`daniwelter/hca-ontology-mappings` (2019, unmaintained). That is the argument
for a general package rather than a 30-line internal module.

But it does **not** belong in `zooma-client`:

1. It is OLS4 access, not Zooma access. Two unrelated API contracts, one
   release cadence, and OLS4 changes independently of ZOOMA.
2. `ebi-ols-client` (v1.1.0) and `olsapy` already exist on PyPI; before writing
   a third OLS client, evaluate those. Only `ebibioservices`-grade gaps justify
   a new one.
3. It cannot be designed well before the Zooma boundary is settled, which is
   what this package is for.

**Consequence to accept:** with scope = Zooma-only, this package is consumed by
exactly one known user (the Galaxy tool). Its honest justification is therefore
"clean core + the traps are encoded once", **not** demonstrated multi-consumer
reuse. That is still worth doing, but it lowers the payoff — hence:

- v1 = `zooma-client`, Zooma only.
- if/when term resolution is needed → a sibling `ols-client` (or reuse an
  existing package), **not** a merged `recetox-ebi` monolith.

If multi-consumer reuse is the actual goal, this is the decision point to
reconsider — see §11 Q3.

---

## 9. Distribution and the Galaxy integration

### Precedent (checked)

- The pattern to copy is `tools/matchms` and `tools/msmetaenhancer`: a
  `<requirements><requirement type="package" version="@TOOL_VERSION@">PKG`
  block, wrapper imports the library. MSMetaEnhancer is the closest analogue: a
  RECETOX-maintained pip package consumed by a RECETOX tool.
- Zooma currently declares `requests 2.32.3` only.
- **`zooma-client` must be installable from the resolver the tool env uses.**
  Conda auto-resolution is the default here; `wtv` is on bioconda (200) and
  `r-recetox-waveica` is on bioconda (200) — so **RECETOX already publishes to
  bioconda**, and there is precedent to follow (`r-recetox-*` naming suggests
  through the R-conversion route, so confirm the Python route).

### Hard gate

> The Galaxy tool **cannot be switched over** until `zooma-client` resolves from
> conda (bioconda or conda-forge) or an explicit pip-installed env is wired in.
> A PyPI-only release is not sufficient.

Sequencing consequence: **PyPI + bioconda first, tool migration second.**
Bioconda build latency (days) should be scheduled, not discovered.

### Packaging

- **Build backend: setuptools + `pyproject.toml`**, src layout. Chosen over
  Poetry because Galaxy tool dependencies resolve transitively and Poetry's
  lockfile is a liability for a leaf library. Note this *differs from*
  `RECETOX/MSMetaEnhancer`, which uses Poetry — a conscious divergence, and
  worth confirming you want to set that precedent for future `zooma`-class
  packages.
- `requires-python = ">=3.11"` (local `python3` is 3.12.3) — enables
  `X | None`, dataclass slots, `Self`. Confirm against the Galaxy tool env's
  Python.
- Runtime deps: `requests` only. **Add nothing else** — no pydantic, no
  tenacity, no httpx. Every added dep is a conda build and a version-resolution
  conflict in the tool env. Dataclasses over pydantic for this reason.
- Dev: `pytest`, `ruff`, `responses` or `pytest-httpx` for HTTP mocking
  (`responses` fits `requests`).
- Version single-sourced; CI publish to PyPI on tag, modeled on
  `MSMetaEnhancer/.github/workflows/publish_pypi.yaml`.
- **Name check before anything else**: `zooma-client` is unclaimed on PyPI and
  on bioconda today — claim it early.

---

## 10. Phased tasks

Each phase is independently reviewable and testable. Ordered so the risky
decision (§7.2) surfaces in Phase 2, not during migration.

### Phase 0 — Scaffolding
- [ ] `pyproject.toml` (setuptools, src layout), `README.md`, `LICENSE`
      (**MIT**, matching `MSMetaEnhancer` — **confirm with RECETOX policy**),
      `.gitignore`, `ruff.toml`
- [ ] `zooma_client/` skeleton + `errors.py` hierarchy + `endpoints.py` constants
- [ ] CI: lint + test matrix on push/PR
- **Validate:** `pipx install .` / `python -c "import zooma_client"` clean in an
  isolated venv; no Galaxy imports; `requests` is the only runtime dep.

### Phase 1 — Models (pure, no I/O)
- [ ] Frozen dataclasses from §3 response shapes: `Mapping`, `Candidate`,
      `Provenance`, `Annotation`, `AnnotatedProperty`, `Preset`, `Source`, `Model`
- [ ] `from_dict` parsers that tolerate missing/null keys
- [ ] Tests: real captured payloads as fixtures — **copy from
      `tools/zooma/test-data/`** plus the live responses in this plan
- **Validate:** parser round-trips against the real payloads; every `| None`
  genuinely exercised (v3 returns `"propertyType": null`, `"uri": null`).

### Phase 2 — Transport + retry ⚠️ decision gate
- [ ] `client.py` with `session=` injection, content-type/shape validation
      (§4.2)
- [ ] `RetryPolicy` + backoff; **decide 4xx-vs-retry (§7.2b)**
- [ ] `health()` pinned to `/v3/api/health` for **both** modes (there is no v2
      health; `/v2/health` returns SPA HTML and would lie)
- [ ] Mocked tests: 4xx / 5xx / 429 / timeout / HTML-instead-of-JSON /
      count-mismatch / non-empty `error` mapping
- **Validate:** a mocked 503 recovers without aborting; a 400 does not hammer
  the server; no test talks to the network.

### Phase 3 — Map mode
- [ ] `map_all()`: positional matching + count check + echoed-value check,
      `deep`-aware limit enforcement (§4.3), `target_ontologies` +
      `include_other_ontologies=False` default + `FilterViolation` (§4.1)
- [ ] Tests: **duplicate input values must stay separate**; empty candidates →
      zero rows; ontology filter actually restricts
      (`["efo"]` → only efo; `["hp","mondo"]` → hp-only, not 12)
- **Validate:** end-to-end against a mock reproducing the recorded 12-candidate
  baseline vs the 4/3-candidate filtered responses.

### Phase 4 — Annotate mode
- [ ] `annotate()` / `annotate_all()`, caching, per-value retry grouping
- [ ] Docstring stating v2 is single-value per call (§4.4) and ignores unknown
      params
- [ ] Tests: cache hit avoids a second call; retry re-queries only missing values
- **Validate:** 3 values at batch size 2 issue exactly 3 annotate calls.

### Phase 5 — Metadata
- [ ] `presets()`, `sources()`, `list_models()`
- **Validate:** parse the live 2-preset / sources / 4-model payloads.

### Phase 6 — Tool migration
- [ ] Add `<requirement type="package">zooma-client</requirement>`; drop
      `requests` from `zooma.xml` (comes in transitively — **decide: keep it
      pinned explicitly, or rely on transitive? keep it; explicit is safer for
      tool env reproducibility**)
- [ ] Rewrite `zooma.py` as: arg parsing → `read_query_values` → `Client(...)`
      with `sink=log_message`, `on_error="skip"` → writer. Target ~100 lines.
- [ ] Keep the stdout format byte-identical so `zooma.xml` assertions pass
- [ ] Re-verify `detect_errors="exit_code"` is still required (§4.5)
- [ ] Re-run all five planemo tests; handle the §7.2b fallout deliberately
- **Validate:** `planemo test` green; **output diff old vs new `zooma.py` on the
  same inputs must be byte-identical** — this is the migration's acceptance
  test, and it is the one thing that proves nothing was silently lost.

### Phase 7 — Release
- [ ] Tag → PyPI (CI). `conda skeleton pypi zooma-client` → bioconda PR.
      **Start this before Phase 6** given build latency (§9).
- [ ] Toolshed `.shed.yml` `homepage_url`/`long_description` update;
      `macros.xml` help text gains "provided by zooma-client vX".
- [ ] Optional follow-up PR: honest v3 column names (§5).

---

## 11. Open questions — answer before Phase 2

1. **Annotate mode at scale.** Is annotate mode expected to run on many values?
   If yes, N sequential v2 calls is the one case where async (or a thread pool
   over `session=`) earns its keep, and it's cheaper to design in now than
   later. If it's effectively legacy, leave it sync forever.
2. **4xx retry semantics (§7.2b).** Adopt "4xx not retryable" and re-baseline
   test 4 (which relies on a permanent 400 to exercise the retry path), or keep
   retrying everything so the existing assertions stand untouched? I recommend
   the former and an explicit, commented test change.
3. **Is multi-consumer reuse the actual goal?** With Zooma-only scope there is
   one known consumer today (§8). If the goal is a shared internal dependency,
   the deferred term-resolution question should be re-opened now.
4. **Where does the repo live** — `RECETOX/zooma-client`, or under your own
   account initially? Affects the bioconda recipe's `home`/`dev_url` and the
   toolshed `remote_repository_url`.

## 12. Risks

| Risk | Mitigation |
|---|---|
| **API is mid-flight.** `zooma2` pushed 2026-09-13; `AUDIT.md` + `api-compat/` show an active v1→v2→v3 migration; README says v3 vote routes are disabled pending abuse controls. Field names may change. | Pin a minimum package version; shape-validate every response (§4.2) so a change is a loud `UnexpectedResponseError`, not silent data loss. Subscribe to `EBISPOT/zooma2` releases. Ask them for an OpenAPI spec — it would make Phases 1–2 mechanical. |
| Retry-semantics change reads as a regression (§7.2b) | Decide explicitly at the Phase 2 gate; change tests with a comment, never silently. |
| Bioconda latency blocks the tool migration (§9) | Start the recipe at Phase 2, not Phase 7. |
| stdout assertions break | Injected sink; byte-identical-output diff as the Phase 6 acceptance test. |
| Upstream has no spec, so client drift is invisible | Keep the live-response fixtures from Phase 1 as a regression suite; add a scheduled "contract probe" script (an `api-compat/detailed_compare.py` analogue) that runs against production read-only. |
| **PR #797 is open and rewrites the extraction source** | Branch the package off `copilot/zooma-make-tool-more-robust` HEAD (`5cdde35e`), or land #797 first. Do not extract from `master` — `master` still has the `textToMap`/`propertyValue` bug that discards every map-mode row. |

## 13. Reference material

- Tool to extract from: `~/dev/galaxytools/tools/zooma/zooma.py` @ `5cdde35e`,
  branch `copilot/zooma-make-tool-more-robust` (PR #797, open, fixes #796).
  Note the local clone is byte-identical to the PR branch on GitHub.
- Upstream: `EBISPOT/zooma2` — `README.md` (env-var limits),
  `api-compat/AUDIT.md`, DTOs under `backend/src/main/java/uk/ac/ebi/zooma2/api/v3/dto/`
  and `.../api/v2/`.
- Packaging pattern: `RECETOX/MSMetaEnhancer` (`pyproject.toml`,
  `.github/workflows/publish_pypi.yaml`); tool-consumer pattern:
  `galaxytools/tools/matchms`, `tools/msmetaenhancer`.
- Related-but-not-this: `ebi-ols-client`, `olsapy`, `bioservices` (no Zooma),
  `ebi-gene-expression-group/perl-atlas-modules` (Perl ZoomaClient),
  `daniwelter/hca-ontology-mappings`, `rsgoncalves/text2term` (different
  service).
- Probing technique for undocumented fields: send a deliberately wrong field and
  read the 400 message — it enumerates every accepted property.
