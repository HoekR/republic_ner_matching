#!/usr/bin/env python3
"""
Fine-tune GysBERT on LOC-annotated 1626-1630 place name data.

Uses pre-annotated location spans from LOC-annotations.json for accurate training.

Usage:
    uv run python finetune_gysberg_loc.py
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
TRAINING_PAIRS_FILE = DATA_DIR / "training_pairs_loc_1626_1630_dedup.parquet"
OUTPUT_DIR = Path("models/gysberg_delegate_ner_loc")

# Model config
MODEL_NAME = "emanjavacas/GysBERT"
BATCH_SIZE = 16
MAX_EPOCHS = 10
LEARNING_RATE = 0.1


def load_training_pairs():
    """Load LOC-annotated training pairs from parquet."""
    print("Loading LOC-annotated training pairs...")
    df = pd.read_parquet(TRAINING_PAIRS_FILE)
    print(f"  Loaded {len(df)} pairs")
    print(f"  Columns: {df.columns.tolist()}")
    print(f"  Entity types: {df['entity_type'].unique()}")
    return df


def format_sentence_with_labels(group_df):
    """
    Convert LOC-annotated training pairs into labeled sentences.
    
    Strategy:
    - Each record has paragraph_text and exact offset of annotation
    - Extract substring at offset as the labeled entity
    - Create Flair Sentence and label the matching token(s)
    
    Returns list of Sentence objects with PLACE labels.
    """
    sentences = []
    MAX_TOKENS = 512  # BERT token limit
    MAX_WORDS = 100   # Conservative truncation
    
    for resolution_id, res_group in tqdm(group_df.groupby('resolution_id'), desc="Formatting", leave=False):
        try:
            # Get paragraph text (should be same for all in group)
            paragraph_text = res_group.iloc[0]['paragraph_texts']
            if not paragraph_text or pd.isna(paragraph_text):
                continue
            
            # Truncate aggressively
            words = str(paragraph_text).split()[:MAX_WORDS]
            truncated_text = ' '.join(words)
            
            # Create sentence from paragraph
            sentence = Sentence(truncated_text, use_tokenizer=True)
            
            # Skip if too long
            if len(sentence.tokens) > MAX_TOKENS:
                continue
            
            # Collect all annotations for this resolution
            mentions = []
            for _, row in res_group.iterrows():
                mentions.append({
                    'htr_span': row['htr_span'],
                    'canonical': row['canonical_entity'],
                    'type': row['entity_type'],
                })
            
            # Label tokens based on exact matching
            for token in sentence.tokens:
                token_text = token.text.lower()
                is_entity = False
                
                for mention in mentions:
                    htr_lower = mention['htr_span'].lower()
                    canonical_lower = mention['canonical'].lower()
                    
                    # Match exact word or canonical form
                    if (token_text == htr_lower or token_text == canonical_lower):
                        label = f"{mention['type'].upper()}"
                        if label == 'PLACE':
                            token.add_label('ner', label)
                            is_entity = True
                            break
                
                if not is_entity:
                    token.add_label('ner', 'O')
            
            sentences.append(sentence)
        
        except Exception as e:
            continue
    
    return sentences


def create_corpus(df, train_ratio=0.7, val_ratio=0.15):
    """
    Create Flair Corpus from training pairs.
    Splits into train/val/test sets by date.
    """
    print("Creating corpus...")
    
    # Group by date to stratify splits
    unique_dates = sorted(df['date'].unique())
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
    train_sentences = format_sentence_with_labels(train_df)
    val_sentences = format_sentence_with_labels(val_df)
    test_sentences = format_sentence_with_labels(test_df)
    
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
    
    # Load embeddings
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
    print("GysBERT Fine-tuning on LOC-Annotated 1626-1630 Data")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    # Load training pairs
    df = load_training_pairs()
    print()
    
    # Create corpus
    corpus = create_corpus(df, train_ratio=0.7, val_ratio=0.15)
    print()
    
    # Fine-tune
    tagger = finetune_model(corpus)
    print()
    
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()
    print("=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Elapsed: {elapsed/60:.1f} minutes")
    print("=" * 70)


if __name__ == "__main__":
    main()
