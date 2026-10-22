"""Endpoint paths and server-side limits for the ZOOMA API.

The paths are appended to the ``base_url`` passed to
:class:`zooma_client.Client`; the default ``DEFAULT_BASE_URL`` points at the
live EBI service.
"""

DEFAULT_BASE_URL = "https://www.ebi.ac.uk/spot/zooma"

# The only real health endpoint. There is no usable v2 health route:
# `/v2/api/health` is gone and any unknown path under `/spot/zooma/`
# answers 200 with the web app's HTML, so it would report healthy no
# matter what. The service reports one overall status, so both v2 and v3
# users check the v3 endpoint.
HEALTH_PATH = "/v3/api/health"

# v3 API.
MAP_PATH = "/v3/api/services/map"
ONTOLOGY_PRESETS_PATH = "/v3/api/ontology-presets"
SOURCES_PATH = "/v3/api/sources"
MODELS_PATH = "/v3/api/models"

# v2 API. The data routes (`/v2/api/properties`, `/v2/api/annotations`)
# are gone; only the annotate service survives.
ANNOTATE_PATH = "/v2/api/services/annotate"

# Server-side limits, from the EBISPOT/zooma2 README.md. The client
# enforces these before any network call so a bad request fails fast with
# a clear message instead of a server 400 after a round trip.
MAX_PROPERTIES = 1000
MAX_DEEP_PROPERTIES = 200
MAX_PROPERTY_TEXT_LENGTH = 1000
MAX_ANNOTATE_TEXT_LENGTH = 50000
MAX_REQUEST_BYTES = 2097152
