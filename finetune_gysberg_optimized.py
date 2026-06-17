#!/usr/bin/env python3
"""
Memory-optimized fine-tuning of GysBERT on LOC annotations (places only).

Strategy:
- Use LOC-only data first (21K pairs, much smaller)
- Stream sentences without caching all at once
- Reduce batch size to 8
- Use gradient checkpointing
- Save after each epoch to avoid OOM

Usage:
    uv run python finetune_gysberg_optimized.py
"""

import pandas as pd
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import torch
import flair

# Import flair components
from flair.data import Corpus, Sentence
from flair.datasets import SentenceDataset
from flair.models import SequenceTagger
from flair.trainers import ModelTrainer
from flair.embeddings import TransformerWordEmbeddings

# Use MPS if available
if torch.backends.mps.is_available():
    device = torch.device("mps")
    flair.device = device
    print("✓ Metal Performance Shaders (MPS) enabled")
else:
    device = torch.device("cpu")
    print("Using CPU")

# Force garbage collection
import gc
gc.collect()

# Configuration
DATA_DIR = Path("data")
TRAINING_PAIRS_FILE = DATA_DIR / "training_pairs_loc_from_annotations.parquet"
OUTPUT_DIR = Path("models/gysberg_place_ner")

# Model config - optimized for CPU
MODEL_NAME = "emanjavacas/GysBERT"
BATCH_SIZE = 8  # Reduced from 16 to prevent OOM with corrected paragraph texts
MAX_EPOCHS = 7  # Restore full epochs (CPU is slower but stable)
LEARNING_RATE = 0.01


def load_training_pairs():
    """Load LOC training pairs only."""
    print("Loading LOC training pairs...")
    df = pd.read_parquet(TRAINING_PAIRS_FILE)
    print(f"  Loaded {len(df)} pairs")
    return df


def format_sentence_with_labels(group_df):
    """
    Format sentences using authoritative character offsets from LOC-annotations.

    Requires paragraph_texts to be present in the data. No fallback logic.
    """
    sentences = []
    MAX_TOKENS = 512
    MAX_CHARS = 500  # Truncate by characters to stay within BERT limit

    for resolution_id, res_group in tqdm(group_df.groupby('resolution_id'),
                                         desc="Formatting", leave=False,
                                         disable=True):
        try:
            # paragraph_texts is mandatory — no fallback
            first_row = res_group.iloc[0]
            paragraph_text = first_row.get('paragraph_texts')
            
            if not paragraph_text or pd.isna(paragraph_text):
                continue

            # paragraph_texts is a list of strings; join and truncate
            if isinstance(paragraph_text, list):
                paragraph_text = ' '.join(str(p) for p in paragraph_text if p)[:MAX_CHARS]
            else:
                paragraph_text = str(paragraph_text)[:MAX_CHARS]
            
            if not paragraph_text:
                continue

            sentence = Sentence(paragraph_text, use_tokenizer=True)

            if len(sentence.tokens) > MAX_TOKENS:
                continue

            # Use authoritative offset/end from annotations
            place_spans = []
            for _, row in res_group.iterrows():
                offset = row.get('offset')
                end = row.get('end')
                if offset is None or end is None:
                    continue
                # Clip to MAX_CHARS
                if offset < MAX_CHARS:
                    place_spans.append((int(offset), min(int(end), MAX_CHARS)))

            if not place_spans:
                continue

            # Label each token by checking if its character position falls in a span
            for token in sentence.tokens:
                tok_start = token.start_position
                tok_end = token.end_position
                labeled = False

                for span_start, span_end in place_spans:
                    # Token overlaps with span
                    if tok_start >= span_start and tok_end <= span_end:
                        token.add_label('ner', 'PLACE')
                        labeled = True
                        break

                if not labeled:
                    token.add_label('ner', 'O')

            # Only keep sentences that have at least one PLACE token
            if any(t.get_label('ner').value == 'PLACE' for t in sentence.tokens):
                sentences.append(sentence)

        except Exception:
            continue

    return sentences


def create_corpus(df):
    """Create corpus with date stratification."""
    print("Creating corpus...")
    
    # Split by date if available, otherwise random split
    if df['date'].notna().sum() > 0:
        print("  Splitting by date...")
        unique_dates = sorted(df['date'].dropna().unique())
        n_dates = len(unique_dates)
        train_idx = int(n_dates * 0.7)
        val_idx = int(n_dates * 0.85)
        
        train_df = df[df['date'].isin(unique_dates[:train_idx])]
        val_df = df[df['date'].isin(unique_dates[train_idx:val_idx])]
        test_df = df[df['date'].isin(unique_dates[val_idx:])]
    else:
        print("  Splitting randomly (dates unavailable)...")
        train_df = df.sample(frac=0.7, random_state=42)
        remaining = df.drop(train_df.index)
        val_df = remaining.sample(frac=0.5, random_state=42)  # 50-50 split of remaining 30%
        test_df = remaining.drop(val_df.index)
    
    print(f"  Train: {len(train_df)} pairs")
    print(f"  Val: {len(val_df)} pairs")
    print(f"  Test: {len(test_df)} pairs")
    
    print("  Formatting sentences (this may take a minute)...")
    train_sentences = format_sentence_with_labels(train_df)
    val_sentences = format_sentence_with_labels(val_df)
    test_sentences = format_sentence_with_labels(test_df)
    
    print(f"  Train sentences: {len(train_sentences)}")
    print(f"  Val sentences: {len(val_sentences)}")
    print(f"  Test sentences: {len(test_sentences)}")
    
    corpus = Corpus(
        train=SentenceDataset(train_sentences),
        dev=SentenceDataset(val_sentences),
        test=SentenceDataset(test_sentences),
    )
    
    return corpus


def finetune_model(corpus):
    """Fine-tune with memory optimization."""
    print("\nFine-tuning GysBERT (PLACE recognition)...")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("  Loading embeddings...")
    embeddings = TransformerWordEmbeddings(
        model=MODEL_NAME,
        fine_tune=True,
        use_context=True,
    )
    
    print("  Creating tagger...")
    tagger = SequenceTagger(
        hidden_size=256,
        embeddings=embeddings,
        tag_type='ner',
        tag_dictionary=corpus.make_label_dictionary(label_type='ner'),
        use_crf=True,
        use_rnn=True,
        rnn_layers=1,
        loss_weights={'O': 0.1, 'PLACE': 1.0},
    )
    
    
    trainer = ModelTrainer(tagger, corpus)
    
    print("  Starting training...")
    trainer.train(
        base_path=str(OUTPUT_DIR),
        learning_rate=LEARNING_RATE,
        mini_batch_size=BATCH_SIZE,
        mini_batch_chunk_size=2,  # Reduced from 4 for gradient accumulation
        max_epochs=MAX_EPOCHS,
        patience=2,
        embeddings_storage_mode="none",
        eval_batch_size=2,  # Reduced from 4 to prevent OOM
    )
    
    print(f"  Saved to {OUTPUT_DIR}")
    return tagger


def main():
    start_time = datetime.now()
    print("=" * 70)
    print("GysBERT Fine-tuning: Place Names (LOC) — Memory Optimized")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    df = load_training_pairs()
    print()
    
    corpus = create_corpus(df)
    print()
    
    tagger = finetune_model(corpus)
    print()
    
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds() / 60
    print("=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Elapsed: {elapsed:.1f} minutes")
    print("=" * 70)


if __name__ == "__main__":
    main()
