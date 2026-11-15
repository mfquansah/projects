"""Embeddings for search by meaning. Brute-force cosine similarity is plenty for ~1,000 notes."""
from __future__ import annotations

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    model_version: str

    def embed(self, texts: list[str]) -> np.ndarray: ...  # shape (n, dim)


class SentenceTransformerEmbedder:
    """Local embeddings. Install: pip install sentence-transformers"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # lazy

        self.model_version = model_name
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, normalize_embeddings=True), dtype=np.float32)


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine_scores(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    q = query / (np.linalg.norm(query) or 1.0)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    return (matrix / norms[:, None]) @ q
