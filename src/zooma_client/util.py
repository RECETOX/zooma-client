"""Small formatting helpers shared by the client and its consumers."""

from collections.abc import Sequence


def preview_values(values: Sequence[str], max_values: int = 5, max_length: int = 40) -> str:
    """Format a bounded preview of ``values`` for log or warning messages.

    Bounds both the number of values shown (``max_values``) and the length
    of each one (``max_length``), so a warning can safely quote arbitrary
    user input — including a 1000-character value rejected by the server.

    The format matches what the Galaxy zooma tool prints for skipped
    batches, so migrating the tool onto this library keeps its stdout
    byte-identical.
    """
    previews = [
        value if len(value) <= max_length else f"{value[:max_length]}..."
        for value in values[:max_values]
    ]
    if len(values) > max_values:
        previews.append(f"... ({len(values) - max_values} more)")
    return ", ".join(repr(value) for value in previews)
