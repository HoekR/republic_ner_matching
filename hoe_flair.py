"""
hoe_flair.py — Flair-based HOE span classifier (stacked layer on top of hoe_classify.py).

This module trains a Flair TextClassifier using **GysBERT** document embeddings
and a per-category label set derived from perscatrep.tsv.  It is the recommended
primary classifier for production use; hoe_classify.py (TF-IDF + regex) serves
as a fast offline baseline that requires no GPU and no model download.

Why GysBERT, not the Flair Dutch NER model?
--------------------------------------------
Flair ships a CoNLL-03-Dutch sequence tagger trained on *modern* Dutch news text
(NRC Handelsblad).  That model's vocabulary and language statistics are completely
wrong for 17th/18th-century resolution language.

`emanjavacas/GysBERT` (Manjavacas & Fonteyn, 2022) is a RoBERTa model trained
exclusively on **historical Dutch** from the DBNL corpus (13th–20th century,
~1 billion tokens), making it the only publicly available contextual model whose
tokeniser and representations actually match the orthography of the Republic
resolutions.  It is loaded via Flair's TransformerDocumentEmbeddings interface,
so no raw HuggingFace code is needed.

Stacking design
---------------
Layer 1 — ``hoe_classify.classify()``  (TF-IDF cosine + regex, instant, no GPU)
    • Confident hits (score ≥ 80) are accepted without calling Flair.
    • Uncertain or 'other' spans are passed to Layer 2.

Layer 2 — ``FlairHOEClassifier.predict()``  (GysBERT fine-tuned on perscatrep)
    • Returns the model's top label and its confidence.
    • Falls back to the Layer 1 result if the model returns < min_confidence.

Usage
-----
Training (once, ~10 minutes on CPU, ~2 min on GPU):
    python hoe_flair.py --train \\
        --perscatrep data/perscatrep.tsv \\
        --model-dir data/hoe_flair_model

Classification (runtime):
    from hoe_flair import FlairHOEClassifier
    clf = FlairHOEClassifier.load("data/hoe_flair_model/final-model.pt")
    canonical, category, confidence = clf.predict("haar hoogh mogende ambassadeur")

Combined stacked call:
    from hoe_flair import classify_stacked
    canonical, category, method, score = classify_stacked("haar hoog mog. extr. envoyé")

Outputs (training)
------------------
    data/hoe_flair_model/
        final-model.pt   — Flair TextClassifier, loadable with Classifier.load()
        training.log     — per-epoch loss/F1
        loss.tsv         — CSV of training metrics
"""

from __future__ import annotations

import pathlib
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent
_PERSCATREP_DEFAULT = _HERE / "data" / "perscatrep.tsv"
_MODEL_DIR_DEFAULT = _HERE / "data" / "hoe_flair_model"

# Category label mapping (perscatrep → Flair label)
# Flair expects string labels; we use the perscatrep categorie values directly.
LABEL_TYPE = "hoe_category"


# ---------------------------------------------------------------------------
# Training data preparation
# ---------------------------------------------------------------------------

def _make_corpus(perscatrep_path: pathlib.Path, seed: int = 42):
    """Convert perscatrep.tsv into a Flair ClassificationCorpus.

    Each ``hoedanigheid_in_tag`` row becomes one Flair Sentence with a
    CORPUS label equal to its ``categorie``.

    The corpus is split 80/10/10 stratified by category so that even rare
    categories (person_family, person_meeting_role) appear in test.
    """
    import pandas as pd
    from flair.data import Corpus, Sentence
    from flair.datasets import SentenceDataset

    df = (
        pd.read_csv(perscatrep_path, sep="\t", dtype=str)
        .dropna(subset=["categorie", "hoedanigheid_in_tag"])
        .sample(frac=1, random_state=seed)
        .reset_index(drop=True)
    )

    def _row_to_sentence(row) -> Sentence:
        s = Sentence(str(row["hoedanigheid_in_tag"]).strip())
        s.add_label(LABEL_TYPE, str(row["categorie"]).strip())
        return s

    all_sentences = [_row_to_sentence(row) for _, row in df.iterrows()]

    # Stratified split — collect per-category indices then 80/10/10 split
    from collections import defaultdict
    cat_idx: dict[str, list[int]] = defaultdict(list)
    for i, row in df.iterrows():
        cat_idx[row["categorie"]].append(i)  # type: ignore[index]

    train_idxs, dev_idxs, test_idxs = [], [], []
    for idxs in cat_idx.values():
        n = len(idxs)
        n_test = max(1, int(n * 0.10))
        n_dev = max(1, int(n * 0.10))
        test_idxs.extend(idxs[:n_test])
        dev_idxs.extend(idxs[n_test: n_test + n_dev])
        train_idxs.extend(idxs[n_test + n_dev:])

    train = SentenceDataset([all_sentences[i] for i in train_idxs])
    dev = SentenceDataset([all_sentences[i] for i in dev_idxs])
    test = SentenceDataset([all_sentences[i] for i in test_idxs])

    return Corpus(train=train, dev=dev, test=test)


# ---------------------------------------------------------------------------
# Classifier wrapper
# ---------------------------------------------------------------------------

class FlairHOEClassifier:
    """Thin wrapper around a trained Flair TextClassifier for HOE classification.

    Parameters
    ----------
    model_path:
        Path to a ``final-model.pt`` produced by ``train()``.
    """

    def __init__(self, model_path: pathlib.Path):
        from flair.nn import Classifier
        self._model = Classifier.load(str(model_path))

    @classmethod
    def load(cls, path: pathlib.Path | str) -> "FlairHOEClassifier":
        return cls(pathlib.Path(path))

    def predict(
        self, text: str, min_confidence: float = 0.50
    ) -> tuple[str, str, float]:
        """Return ``(label, category, confidence)`` for *text*.

        If the top-label confidence is below *min_confidence*, returns
        ``('other', 'other', confidence)`` to signal that the stacked
        fallback should be consulted.

        ``label`` is the Flair label value (same as perscatrep ``categorie``).
        ``category`` is identical — kept separate so the stacked interface
        can carry a canonical-form field in future.
        """
        from flair.data import Sentence

        sentence = Sentence(str(text).strip())
        self._model.predict(sentence)
        labels = sentence.labels
        if not labels:
            return "other", "other", 0.0
        top = max(labels, key=lambda lb: lb.score)
        if top.score < min_confidence:
            return "other", "other", float(top.score)
        return top.value, top.value, float(top.score)


# ---------------------------------------------------------------------------
# Training entry point
# ---------------------------------------------------------------------------

def train(
    perscatrep_path: pathlib.Path = _PERSCATREP_DEFAULT,
    model_dir: pathlib.Path = _MODEL_DIR_DEFAULT,
    max_epochs: int = 20,
    lr: float = 2e-5,
    batch_size: int = 16,
    seed: int = 42,
) -> None:
    """Fine-tune GysBERT on perscatrep for HOE category classification.

    GysBERT (``emanjavacas/GysBERT``) is a RoBERTa model trained on 1B tokens
    of historical Dutch (DBNL corpus, 13th–20th century).  It is the only
    publicly available contextual model suited for 17th/18th-century Dutch text
    — *not* the Flair built-in Dutch NER model, which is trained on modern news.

    The fine-tuned model is saved to *model_dir/final-model.pt*.
    """
    from flair.embeddings import TransformerDocumentEmbeddings
    from flair.models import TextClassifier
    from flair.trainers import ModelTrainer

    model_dir = pathlib.Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    print("Loading corpus from perscatrep.tsv …", file=sys.stderr)
    corpus = _make_corpus(perscatrep_path, seed=seed)
    label_dict = corpus.make_label_dictionary(label_type=LABEL_TYPE)
    print(
        f"  train={len(corpus.train):,}  dev={len(corpus.dev):,}  "
        f"test={len(corpus.test):,}  labels={list(label_dict.get_items())}",
        file=sys.stderr,
    )

    print("Loading GysBERT embeddings …", file=sys.stderr)
    embeddings = TransformerDocumentEmbeddings(
        model="emanjavacas/GysBERT",
        fine_tune=True,
        layers="-1",
        layer_mean=False,
    )

    classifier = TextClassifier(
        embeddings=embeddings,
        label_dictionary=label_dict,
        label_type=LABEL_TYPE,
        multi_label=False,
    )

    trainer = ModelTrainer(classifier, corpus)
    trainer.fine_tune(
        base_path=model_dir,
        max_epochs=max_epochs,
        learning_rate=lr,
        mini_batch_size=batch_size,
        save_final_model=True,
    )
    print(f"Model saved → {model_dir}/final-model.pt", file=sys.stderr)


# ---------------------------------------------------------------------------
# Stacked interface (Layer 1 + Layer 2)
# ---------------------------------------------------------------------------

_FLAIR_CLASSIFIER: Optional[FlairHOEClassifier] = None


def init_flair(model_path: pathlib.Path | str) -> None:
    """Load and cache the Flair classifier for use by ``classify_stacked()``."""
    global _FLAIR_CLASSIFIER
    _FLAIR_CLASSIFIER = FlairHOEClassifier.load(pathlib.Path(model_path))


def classify_stacked(
    text: str,
    layer1_threshold: int = 70,
    layer1_confident: int = 80,
    flair_min_confidence: float = 0.50,
) -> tuple[str, str, str, int]:
    """Two-layer HOE classification.

    Layer 1  — ``hoe_classify.classify()`` (TF-IDF store / regex / fuzzy).
    Layer 2  — ``FlairHOEClassifier`` (GysBERT fine-tuned on perscatrep).

    The Flair layer is only invoked when Layer 1 is uncertain (score < 80)
    or returns 'other'.  This keeps the common case fast.

    Returns ``(canonical, category, method, score)`` — same contract as
    ``hoe_classify.classify()``.

    method values:
      'tfidf'    — TF-IDF store, confident
      'keyword'  — regex rule, confident
      'flair'    — GysBERT classifier
      'fuzzy'    — token_set_ratio (last resort)
      'other'    — all layers below threshold
    """
    import hoe_classify

    canonical, cat, method, score = hoe_classify.classify(text, layer1_threshold)

    # Layer 1 confident → done
    if score >= layer1_confident and cat != "other":
        return canonical, cat, method, score

    # Layer 2 — Flair
    if _FLAIR_CLASSIFIER is not None:
        flair_cat, _, confidence = _FLAIR_CLASSIFIER.predict(text, flair_min_confidence)
        if flair_cat != "other":
            # canonical is still the Layer 1 canonical (best available)
            return canonical, flair_cat, "flair", round(confidence * 100)

    # Both layers uncertain — return Layer 1 result as-is
    return canonical, cat, method, score


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Train or run the Flair HOE classifier (stacked over hoe_classify)."
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Fine-tune GysBERT on perscatrep.tsv and save the model.",
    )
    parser.add_argument(
        "--perscatrep",
        default=str(_PERSCATREP_DEFAULT),
        type=pathlib.Path,
    )
    parser.add_argument(
        "--model-dir",
        default=str(_MODEL_DIR_DEFAULT),
        type=pathlib.Path,
    )
    parser.add_argument("--epochs", default=20, type=int)
    parser.add_argument("--lr", default=2e-5, type=float)
    parser.add_argument("--batch-size", default=16, type=int)
    args = parser.parse_args(argv)

    if args.train:
        train(
            perscatrep_path=args.perscatrep,
            model_dir=args.model_dir,
            max_epochs=args.epochs,
            lr=args.lr,
            batch_size=args.batch_size,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
