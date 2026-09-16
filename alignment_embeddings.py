#!/usr/bin/env python3
"""Semantic embedding and similarity utilities for resolution alignment.

Computes dense or sub-linear n-gram semantic similarity matrices between
enriched summary texts and flat resolution texts for sequence alignment.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Literal

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


EmbeddingBackend = Literal["auto", "tfidf", "ollama", "transformers"]


class AlignmentEmbedder:
    """Computes pairwise semantic similarities between resolution summaries and full texts."""

    def __init__(
        self,
        backend: EmbeddingBackend = "auto",
        model_name: str = "emanjavacas/GysBERT",
        ollama_model: str = "nomic-embed-text",
        ollama_url: str = "http://localhost:11434/api/embed",
    ) -> None:
        self.requested_backend = backend
        self.model_name = model_name
        self.ollama_model = ollama_model
        self.ollama_url = ollama_url
        self.active_backend = self._detect_backend(backend)
        self._hf_model = None
        self._hf_tokenizer = None

    def _detect_backend(self, backend: EmbeddingBackend) -> str:
        if backend == "auto":
            try:
                import torch
                import transformers
                return "transformers"
            except ImportError:
                pass
            return "tfidf"
        return backend

    def _get_hf_pipeline(self) -> tuple[Any, Any]:
        if self._hf_model is None or self._hf_tokenizer is None:
            import torch
            from transformers import AutoModel, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModel.from_pretrained(self.model_name)
            device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
            model.eval()
            self._hf_tokenizer = tokenizer
            self._hf_model = (model, device)
        return self._hf_model, self._hf_tokenizer

    def _embed_transformers(self, texts: list[str]) -> np.ndarray:
        import torch

        (model, device), tokenizer = self._get_hf_pipeline()
        cleaned_texts = [t.strip() if t and t.strip() else " " for t in texts]
        inputs = tokenizer(
            cleaned_texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            outputs = model(**inputs)
            # Mean pooling over attention mask
            token_embeddings = outputs.last_hidden_state
            input_mask_expanded = inputs["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
            sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
            sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
            mean_pooled = sum_embeddings / sum_mask
            # Normalize
            normalized = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)
            return normalized.cpu().numpy()

    def _embed_ollama(self, texts: list[str]) -> np.ndarray | None:
        payload = json.dumps({"model": self.ollama_model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            self.ollama_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            embeddings = data.get("embeddings")
            if embeddings:
                arr = np.array(embeddings, dtype=np.float32)
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms[norms == 0] = 1e-9
                return arr / norms
        except Exception:
            return None
        return None

    def compute_similarity_matrix(self, enriched_texts: list[str], flat_texts: list[str]) -> np.ndarray:
        """Compute an (N x M) similarity matrix between enriched and flat resolution texts."""
        n = len(enriched_texts)
        m = len(flat_texts)
        if n == 0 or m == 0:
            return np.zeros((n, m), dtype=np.float32)

        if self.active_backend == "transformers":
            try:
                emb_enr = self._embed_transformers(enriched_texts)
                emb_flat = self._embed_transformers(flat_texts)
                sim = np.dot(emb_enr, emb_flat.T)
                return np.clip(sim, 0.0, 1.0)
            except Exception:
                # Graceful fallback to TF-IDF
                pass

        if self.active_backend == "ollama":
            emb_enr = self._embed_ollama(enriched_texts)
            emb_flat = self._embed_ollama(flat_texts)
            if emb_enr is not None and emb_flat is not None:
                sim = np.dot(emb_enr, emb_flat.T)
                return np.clip(sim, 0.0, 1.0)

        # Robust default: Character + Word sublinear TF-IDF similarity
        all_corpus = [t if t and t.strip() else " " for t in enriched_texts + flat_texts]
        vectorizer_word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        vectorizer_char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)

        vec_w = vectorizer_word.fit_transform(all_corpus)
        vec_c = vectorizer_char.fit_transform(all_corpus)

        sim_w = cosine_similarity(vec_w[:n], vec_w[n:])
        sim_c = cosine_similarity(vec_c[:n], vec_c[n:])

        # Combined word (0.4) and character skip-gram (0.6) similarity
        sim_matrix = (0.4 * sim_w) + (0.6 * sim_c)
        return np.clip(sim_matrix, 0.0, 1.0)
