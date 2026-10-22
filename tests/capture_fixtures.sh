#!/usr/bin/env bash
# One-off helper used to capture live ZOOMA responses as test fixtures.
# Read-only against production. Run from the repo root: bash tests/capture_fixtures.sh
set -euo pipefail

BASE="https://www.ebi.ac.uk/spot/zooma"
DIR="$(cd "$(dirname "$0")" && pwd)/fixtures"

fetch() {
    local name="$1" url="$2"
    curl -sS -H "Accept: application/json" "$url" -o "$DIR/$name"
    echo "$name: $(wc -c < "$DIR/$name") bytes"
}

fetch health.txt "$BASE/v3/api/health"
fetch presets.json "$BASE/v3/api/ontology-presets"
fetch sources.json "$BASE/v3/api/sources"
fetch models.json "$BASE/v3/api/models"

# v3 map: two values, one repeated, to pin positional echoing of duplicates.
curl -sS -X POST "$BASE/v3/api/services/map" \
    -H "Accept: application/json" -H "Content-Type: application/json" \
    -d '{"properties":[{"textToMap":"body mass index"},{"textToMap":"asthma"},{"textToMap":"body mass index"}]}' \
    -o "$DIR/map_duplicate_values.json"
echo "map_duplicate_values.json: $(wc -c < "$DIR/map_duplicate_values.json") bytes"

# v3 map: ontology filter that must actually restrict.
curl -sS -X POST "$BASE/v3/api/services/map" \
    -H "Accept: application/json" -H "Content-Type: application/json" \
    -d '{"properties":[{"textToMap":"body mass index"}],"targetOntologies":["efo"],"includeOtherOntologies":false}' \
    -o "$DIR/map_filtered_efo.json"
echo "map_filtered_efo.json: $(wc -c < "$DIR/map_filtered_efo.json") bytes"

# v2 annotate (single value per call).
curl -sS "$BASE/v2/api/services/annotate?propertyValue=asthma" \
    -H "Accept: application/json" -o "$DIR/annotate_asthma.json"
echo "annotate_asthma.json: $(wc -c < "$DIR/annotate_asthma.json") bytes"

# The SPA trap: an unknown path under /spot/zooma/ returns 200 HTML.
curl -sS "$BASE/v2/health" -o "$DIR/spa_html.html"
echo "spa_html.html: $(wc -c < "$DIR/spa_html.html") bytes"
