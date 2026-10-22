"""Live smoke test for zooma-client (read-only). Run from the repo root:

    .venv/bin/python smoke_test.py

Checks the plan's success criterion 3: usable without Galaxy, against the
live API, in about ten lines.
"""
from zooma_client import Client

client = Client()
assert client.health()

mappings = list(client.map_all(["body mass index", "asthma"], target_ontologies=["efo"]))
assert [m.text_to_map for m in mappings] == ["body mass index", "asthma"]
for mapping in mappings:
    for candidate in mapping.candidates:
        print(mapping.text_to_map, "->", candidate.term_id, candidate.label, candidate.confidence)

annotations = client.annotate("asthma")
print(f"annotate('asthma') -> {len(annotations)} annotations, "
      f"first tags: {annotations[0].semantic_tags}")

print(f"presets: {[p.name for p in client.presets()]}")
print(f"models with can_embed: {[m.name for m in client.list_models() if m.can_embed]}")
print("SMOKE TEST OK")
