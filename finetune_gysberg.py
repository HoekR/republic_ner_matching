#!/usr/bin/env python3
"""
Fine-tune GysBERT on 1626-1630 delegate mention training pairs.

Strategy:
- Load deduplicated training pairs
- Format as sequence labeling dataset (BIO tags for entity spans)
- Fine-tune emanjavacas/GysBERT using flair
- Save model checkpoints for inference

Usage:
    uv run python finetune_gysberg.py
"""

import json
from pathlib import Path
import pandas as pd
from datetime import datetime
from tqdm import tqdm
import torch
import flair

# Import flair components
from flair.data import Corpus, Sentence, Token, Label
from flair.datasets import SentenceDataset
from flair.models import SequenceTagger
from flair.trainers import ModelTrainer
from flair.embeddings import TransformerWordEmbeddings

# Set device to Metal (MPS) if available, otherwise CPU
if torch.backends.mps.is_available():
    device = torch.device("mps")
    flair.device = device
    print("✓ Metal Performance Shaders (MPS) enabled for GPU acceleration")
else:
    device = torch.device("cpu")
    print("! Metal not available, using CPU")


# Configuration
DATA_DIR = Path("data")
TRAINING_PAIRS_FILE = DATA_DIR / "training_pairs_1626_1630_dedup.parquet"
OUTPUT_DIR = Path("models/gysberg_delegate_ner")

# Model config
MODEL_NAME = "emanjavacas/GysBERT"
BATCH_SIZE = 16
MAX_EPOCHS = 10
LEARNING_RATE = 0.1


def load_training_pairs():
    """Load deduplicated training pairs from parquet."""
    print("Loading training pairs...")
    df = pd.read_parquet(TRAINING_PAIRS_FILE)
    print(f"  Loaded {len(df)} pairs")
    print(f"  Columns: {df.columns.tolist()}")
    print(f"  Entity types: {df['entity_type'].unique()}")
    return df


def load_resolutions(training_pairs_df):
    """Load only resolutions referenced in training pairs."""
    print("Loading resolutions...")
    resolutions_parquet = DATA_DIR / "resolutions_flat.parquet"
    if not resolutions_parquet.exists():
        raise FileNotFoundError(f"Resolutions file not found: {resolutions_parquet}")
    
    # Only load resolutions that appear in training pairs
    needed_ids = set(training_pairs_df['resolution_id'].unique())
    print(f"  Filtering to {len(needed_ids)} resolutions from training pairs...")
    
    # Read with filter
    resolutions_df = pd.read_parquet(
        resolutions_parquet, 
        filters=[('id', 'in', list(needed_ids))]
    )
    
    # Fallback if filter didn't work (depends on parquet engine)
    if len(resolutions_df) < len(needed_ids) * 0.5:
        print("  Filter didn't reduce enough; loading full dataset...")
        resolutions_df = pd.read_parquet(resolutions_parquet)
        resolutions_df = resolutions_df[resolutions_df['id'].isin(needed_ids)]
    
    print(f"  Loaded {len(resolutions_df)} resolutions ({(1 - len(resolutions_df)/692156)*100:.1f}% reduction)")
    return resolutions_df


def format_sentence_with_labels(group_df, resolutions_df):
    """
    Convert training pairs into labeled sentences using actual resolution text.
    
    Strategy:
    - For each resolution ID, get the paragraph text
    - Truncate aggressively to account for BERT subword tokenization
    - Create Flair Sentence with token-level labels
    
    Returns list of Sentence objects with labels.
    """
    sentences = []
    MAX_TOKENS = 512  # BERT token limit
    MAX_WORDS = 100  # Conservative: ~250-300 tokens after BERT tokenization
    
    # Group by resolution_id to create sentences from actual paragraph text
    for resolution_id, res_group in tqdm(group_df.groupby('resolution_id'), desc="Formatting", leave=False):
        try:
            # Get paragraph text from resolutions
            para_rows = resolutions_df[resolutions_df['id'] == resolution_id]
            if len(para_rows) == 0:
                continue
            
            paragraph_text = para_rows.iloc[0]['paragraph_texts']
            if not paragraph_text or pd.isna(paragraph_text):
                continue
            
            # Truncate aggressively to prevent BERT token overflow
            # 100 words typically → 250-300 BERT tokens (safe margin)
            words = str(paragraph_text).split()[:MAX_WORDS]
            truncated_text = ' '.join(words)
            
            # Create sentence from paragraph
            sentence = Sentence(truncated_text, use_tokenizer=True)
            
            # Skip if sentence becomes too long after tokenization
            if len(sentence.tokens) > MAX_TOKENS:
                continue
            
            # Collect all mentions for this resolution
            mentions = []
            for _, row in res_group.iterrows():
                mentions.append({
                    'htr_span': row['htr_span'],
                    'canonical': row['canonical_entity'],
                    'type': row['entity_type'],
                })
            
            # Label tokens based on exact matching to htr_spans
            for token in sentence.tokens:
                token_text = token.text.lower()
                is_entity = False
                
                for mention in mentions:
                    htr_lower = mention['htr_span'].lower()
                    canonical_lower = mention['canonical'].lower()
                    
                    # Only match complete word matches (not substrings)
                    if (token_text == htr_lower or token_text == canonical_lower):
                        label = f"{mention['type'].upper()}"
                        # Ensure label is valid
                        if label in ['PLACE', 'NAME']:
                            token.add_label('ner', label)
                            is_entity = True
                            break
                
                if not is_entity:
                    token.add_label('ner', 'O')
            
            sentences.append(sentence)
        
        except Exception as e:
            # Skip problematic resolutions
            continue
    
    return sentences


def create_corpus(df, resolutions_df, train_ratio=0.8, val_ratio=0.1):
    """
    Create Flair Corpus from training pairs.
    Uses actual paragraph text from resolutions for sentence creation.
    Splits into train/val/test sets.
    """
    print("Creating corpus...")
    
    # Group by date to stratify splits
    unique_dates = df['date'].unique()
    n_dates = len(unique_dates)
    split_idx_train = int(n_dates * train_ratio)
    split_idx_val = int(n_dates * (train_ratio + val_ratio))
    
    train_dates = set(unique_dates[:split_idx_train])
    val_dates = set(unique_dates[split_idx_train:split_idx_val])
    test_dates = set(unique_dates[split_idx_val:])
    
    train_df = df[df['date'].isin(train_dates)]
    val_df = df[df['date'].isin(val_dates)]
    test_df = df[df['date'].isin(test_dates)]
    
    print(f"  Train: {len(train_df)} pairs ({len(train_dates)} dates)")
    print(f"  Val: {len(val_df)} pairs ({len(val_dates)} dates)")
    print(f"  Test: {len(test_df)} pairs ({len(test_dates)} dates)")
    
    # Format sentences
    print("Formatting sentences...")
    train_sentences = format_sentence_with_labels(train_df, resolutions_df)
    val_sentences = format_sentence_with_labels(val_df, resolutions_df)
    test_sentences = format_sentence_with_labels(test_df, resolutions_df)
    
    print(f"  Train sentences: {len(train_sentences)}")
    print(f"  Val sentences: {len(val_sentences)}")
    print(f"  Test sentences: {len(test_sentences)}")
    
    # Create Corpus
    corpus = Corpus(
        train=SentenceDataset(train_sentences),
        dev=SentenceDataset(val_sentences),
        test=SentenceDataset(test_sentences),
    )
    
    return corpus


def finetune_model(corpus):
    """Fine-tune GysBERT on corpus."""
    print("\nFine-tuning GysBERT...")
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load embeddings (transformer-based)
    print(f"  Loading {MODEL_NAME}...")
    embeddings = TransformerWordEmbeddings(
        model=MODEL_NAME,
        fine_tune=True,
        use_context=True,
    )
    
    # Create tagger
    print("  Creating sequence tagger...")
    tagger = SequenceTagger(
        hidden_size=256,
        embeddings=embeddings,
        tag_type='ner',
        tag_dictionary=corpus.make_label_dictionary(label_type='ner'),
        use_crf=True,
        use_rnn=True,
        rnn_layers=1,
    )
    
    # Create trainer
    trainer = ModelTrainer(tagger, corpus)
    
    # Train
    print("  Starting training...")
    trainer.train(
        base_path=str(OUTPUT_DIR),
        learning_rate=LEARNING_RATE,
        mini_batch_size=BATCH_SIZE,
        max_epochs=MAX_EPOCHS,
        patience=3,
    )
    
    print(f"  Model saved to {OUTPUT_DIR}")
    return tagger


def main():
    """Main fine-tuning pipeline."""
    start_time = datetime.now()
    print("=" * 70)
    print("GysBERT Fine-tuning on 1626-1630 Delegate Mention Data")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    # Load training pairs
    df = load_training_pairs()
    print()
    
    # Load resolutions for paragraph context (only needed ones)
    resolutions_df = load_resolutions(df)
    print()
    
    # Create corpus
    corpus = create_corpus(df, resolutions_df, train_ratio=0.7, val_ratio=0.15)
    print()
    
    # Fine-tune
    tagger = finetune_model(corpus)
    print()
    
    # Evaluate on test set
    print("Evaluating on test set...")
    result = tagger.evaluate(corpus.test, out_path=OUTPUT_DIR / "test_results.txt")
    print(f"  Precision: {result.scores_by_class['ner'].prec:.3f}")
    print(f"  Recall: {result.scores_by_class['ner'].rec:.3f}")
    print(f"  F1: {result.scores_by_class['ner'].fscore:.3f}")
    
    end_time = datetime.now()
    duration = end_time - start_time
    print("\n" + "=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {duration.total_seconds():.1f} seconds")
    print("=" * 70)


if __name__ == '__main__':
    main()
