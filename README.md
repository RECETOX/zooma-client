# zooma-client

A small, dependency-light Python client for [ZOOMA](https://www.ebi.ac.uk/spot/zooma),
the EBI service that maps free-text property values to ontology terms.

The package wraps both generations of the API behind one synchronous client:

| API | Method | Returns |
|---|---|---|
| v3 `POST /v3/api/services/map` | `Client.map_all()` | `Mapping` → `Candidate` (batched, positional) |
| v2 `GET /v2/api/services/annotate` | `Client.annotate()` / `annotate_all()` | `Annotation` (one request per value) |
| v3 `GET /v3/api/ontology-presets` | `Client.presets()` | `Preset` |
| v3 `GET /v3/api/sources` | `Client.sources()` | `Source` |
| v3 `GET /v3/api/models` | `Client.list_models()` | `Model` |
| v3 `GET /v3/api/health` | `Client.health()` | `bool` (raises if down) |

## Why this package exists

ZOOMA has no published OpenAPI spec and several behaviours that silently
produce wrong results if you code against it naively. The client encodes
those traps once, so no consumer has to know about them:

- **`targetOntologies` fails open.** The parameter is *additive, not
  restrictive*: sending it alone returns exactly the same candidates as no
  filter at all. It only restricts in combination with
  `includeOtherOntologies: false`, which `map_all()` sends by default
  whenever `target_ontologies` is non-empty. The client then verifies the
  returned candidates actually stay inside the requested set and raises
  `FilterViolation` if the server fails to apply the filter.
- **A 200 response can be the web app.** Any unknown path under
  `/spot/zooma/` answers HTTP 200 with the SPA's HTML. Every response is
  validated by content type and payload shape before parsing; a 200 is
  never trusted on its own.
- **Results are positional.** The v3 map endpoint answers with one mapping
  per submitted value, echoed in `textToMap`. The client checks the
  mapping count and the echoed value on every response, so duplicate
  inputs stay separate instead of being merged.
- **Server limits are enforced client-side.** 1000 properties per request
  (200 in `deep` mode), 1000 characters per value, 2 MiB per request —
  validated before any network call, with clear error messages.
- **4xx is not retried.** Retryable statuses (429, 5xx) and transport
  errors are retried per `RetryPolicy`; a 400 is permanent and fails fast
  instead of hammering the server.

The client is deliberately silent: it never writes to stdout/stderr and
never configures logging. Progress and skip warnings go to an injected
`sink` callable (default: discarded) — pass `print` or a logger method if
you want them.

## Installation

```bash
pip install zooma-client
```

Requires Python 3.11+. The only runtime dependency is `requests`.

## Quickstart

```python
from zooma_client import Client

client = Client()
assert client.health()

for mapping in client.map_all(["body mass index", "asthma"], target_ontologies=["efo"]):
    for candidate in mapping.candidates:
        print(mapping.text_to_map, "->", candidate.term_id, candidate.label, candidate.confidence)

for annotation in client.annotate_all(["asthma", "lung cancer"]):
    print(annotation.property.property_value, annotation.semantic_tags, annotation.confidence)

# Ontology selection also works in annotate mode (v2 `filter` parameter):
for annotation in client.annotate("asthma", target_ontologies=["efo"], defining_only=True):
    print(annotation.semantic_tags, annotation.confidence)
```

`map_all` and `annotate_all` are lazy iterators yielding one result group
per input value in submission order — values whose batch failed are simply
absent from the output (with `on_error="skip"`, the default).

## Error handling

Everything raised derives from `ZoomaError`:

| Exception | Meaning |
|---|---|
| `ServiceUnavailableError` | health check failed, or too many consecutive batches failed |
| `RequestError` | transport-level failure or retryable HTTP status (429, 5xx) |
| `InvalidRequestError` | client-side validation failure or non-retryable 4xx |
| `UnexpectedResponseError` | wrong content type / shape / count mismatch |
| `FilterViolation` | returned candidates outside the requested `target_ontologies` |

`InvalidRequestError` and `UnexpectedResponseError` also subclass
`ValueError`.

## Retry policy

The default `RetryPolicy` matches the Galaxy zooma tool's behaviour: two
attempts per batch, no backoff, a batch that fails twice is skipped, and
two consecutive skipped batches abort the run. Tune it on the client:

```python
from zooma_client import Client, RetryPolicy

client = Client(
    retry=RetryPolicy(max_attempts=4, max_consecutive_failures=3, backoff=1.0),
    sink=print,  # see retry/skip warnings on stdout
)
```

## Notes on the v2 annotate endpoint

`annotate()` accepts a single `propertyValue` per call and silently ignores
*unknown* query parameters, so there is no request batching at that level.
`annotate_all(batch_size=...)` therefore only groups values for
retry/skip purposes; the values are cached, so a retried batch re-queries
only what is still missing and duplicates are queried exactly once.

Ontology selection **is** supported in annotate mode, through the endpoint's
`filter` query parameter (undocumented publicly; the contract is the
`V2FilterDto` parser in `EBISPOT/zooma2`). The client exposes it as
structured options on `annotate()` / `annotate_all()`:

- `target_ontologies=["efo", "hp"]` — a **hard** ontology filter (unlike
  v3, this does not fail open). Returned annotations are verified against
  the requested set (`FilterViolation` otherwise).
- `defining_only=True` — restrict to the ontologies' own namespaces,
  excluding terms they import.
- `required_sources=["gwas"]` / `preferred_sources=["atlas"]` — restrict
  or prefer curated datasources (no effect on ontology-backed matches).

Two quirks to know: a set ontology filter can *increase* the result count,
because it triggers the server's deep search when the shallow search
misses the target ontology; and `ontologies:[none]` is a legacy sentinel
meaning "no restriction" (not exposed — simply omit the option).

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
```

No test talks to the network: all HTTP traffic is mocked with
[`responses`](https://github.com/getsentry/responses) against payloads
captured from the live service in `tests/fixtures/` (see
`tests/capture_fixtures.sh` for how they were produced — a read-only
"contract probe" you can re-run to detect API drift).

## License

MIT — see [LICENSE](LICENSE).
