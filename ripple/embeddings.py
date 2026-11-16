"""Turn text into vectors with a small local model (no API key needed).

Relate stores and searches vectors but does not compute them, so we do it
here with fastembed (bge-small-en-v1.5, 384 numbers per text, runs on CPU).
The model is downloaded once, on first use (about 130 MB).

If fastembed or the model is unavailable, embed() returns None and the rest
of the app falls back to full-text search only.
"""

import os
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384

_model = None
_unavailable = False


def embed(texts: list[str]) -> list[list[float]] | None:
    """Return one vector per text, or None when embeddings are unavailable."""
    global _model, _unavailable
    # RIPPLE_NO_EMBEDDINGS=1 forces the full-text-only mode (used in tests).
    if _unavailable or os.environ.get("RIPPLE_NO_EMBEDDINGS") == "1":
        return None
    try:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(MODEL_NAME, cache_dir=str(Path.home() / ".cache" / "fastembed"))
        # Rounded so the stored graph does not change on tiny float noise.
        return [[round(float(x), 6) for x in vector] for vector in _model.embed(texts)]
    except Exception as error:  # missing package, no network for the download...
        _unavailable = True
        print(f"[ripple] embeddings unavailable ({type(error).__name__}), using full-text search only")
        return None
