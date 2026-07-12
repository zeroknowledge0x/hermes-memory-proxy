"""Embedding service — local, model-agnostic (DECISIONS.md D-006).

bge-small-en-v1.5 via fastembed (ONNX, no PyTorch). Dim 384 = LOCKED to
schema. Lazy-loads the model on first use.
"""
from __future__ import annotations

from typing import Iterable

# Multilingual (supports Bahasa Indonesia) — dim 384, ~0.22GB.
# Chosen over bge-small-en (English-only) per DECISIONS.md D-014.
_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_EXPECTED_DIM = 384


class EmbeddingService:
    def __init__(self, model_name: str = _DEFAULT_MODEL, dim: int = _EXPECTED_DIM):
        self.model_name = model_name
        self.dim = dim
        self._model = None

    def _ensure(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name)
        return self._model

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        model = self._ensure()
        out = [vec.tolist() for vec in model.embed(list(texts))]
        for v in out:
            if len(v) != self.dim:
                raise ValueError(
                    f"Embedding dim mismatch: got {len(v)}, expected {self.dim} "
                    f"(model={self.model_name}). Schema is LOCKED to {self.dim}."
                )
        return out

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @staticmethod
    def to_pgvector(vec: list[float]) -> str:
        """Render a python list as a pgvector literal: '[0.1,0.2,...]'."""
        return "[" + ",".join(repr(float(x)) for x in vec) + "]"
