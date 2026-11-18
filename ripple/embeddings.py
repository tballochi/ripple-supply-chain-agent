"""Turn text into vectors with a small local model (no API key needed).

Relate stores and searches vectors but does not compute them, so we do it
here with fastembed (bge-small-en-v1.5, 384 numbers per text, runs on CPU).

Download the model once (about 70 MB) before the first run:

    python -m ripple.embeddings --download

If the model is not there and cannot be downloaded quickly (no network, a
firewall...), embed() returns None and the rest of the app falls back to
full-text search only. That decision is taken once per process: one short
download attempt, one line printed, no retries on every question.
"""

import logging
import os
import sys
import time
import warnings
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
CACHE_DIR = Path(os.environ.get("RIPPLE_MODEL_CACHE", Path.home() / ".cache" / "fastembed"))
DOWNLOAD_TIMEOUT_S = 10  # per network request during the one download attempt

_model = None
_unavailable = False


def _quiet() -> None:
    """Silence fastembed and Hugging Face: we print our own single line."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", str(DOWNLOAD_TIMEOUT_S))
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(DOWNLOAD_TIMEOUT_S))
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message="Cannot enable progress bars")
    try:
        from loguru import logger  # fastembed logs through loguru
        logger.disable("fastembed")
    except ImportError:
        pass


def _load(local_only: bool):
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR), local_files_only=local_only)


def _download_once():
    """One download attempt, no retries (fastembed would retry for ~40 s)."""
    from fastembed import TextEmbedding
    model_class = next(c for c in TextEmbedding.EMBEDDINGS_REGISTRY
                       if any(m.model == MODEL_NAME for m in c._list_supported_models()))
    description = next(m for m in model_class._list_supported_models() if m.model == MODEL_NAME)
    model_class.download_model(description, str(CACHE_DIR), retries=1)
    return _load(local_only=True)


def get_model():
    """The loaded model, or None when it is unavailable (decided once)."""
    global _model, _unavailable
    if _model is not None or _unavailable:
        return _model
    _quiet()
    try:
        _model = _load(local_only=True)  # already downloaded: no network at all
    except Exception:
        try:
            _model = _download_once()
        except Exception as error:
            _unavailable = True
            print(f"[ripple] Embedding model unavailable ({type(error).__name__}): using full-text "
                  "search only. Run `python -m ripple.embeddings --download` to enable "
                  "search by meaning.", file=sys.stderr)
    return _model


def embed(texts: list[str]) -> list[list[float]] | None:
    """Return one vector per text, or None when embeddings are unavailable."""
    # RIPPLE_NO_EMBEDDINGS=1 forces the full-text-only mode (tests, CI).
    if os.environ.get("RIPPLE_NO_EMBEDDINGS") == "1":
        return None
    model = get_model()
    if model is None:
        return None
    # Rounded so the stored graph does not change on tiny float noise.
    return [[round(float(x), 6) for x in vector] for vector in model.embed(texts)]


if __name__ == "__main__":
    if "--download" not in sys.argv[1:]:
        sys.exit("Usage: python -m ripple.embeddings --download")
    started = time.time()
    if get_model() is None:
        sys.exit(1)
    print(f"Model {MODEL_NAME} ready in {CACHE_DIR} ({time.time() - started:.1f} s).")
