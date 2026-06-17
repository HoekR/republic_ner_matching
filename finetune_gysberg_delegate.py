#!/usr/bin/env python3
"""
GPU-optimized fine-tuning of GysBERT on DELEGATE names (PER annotations).
Designed for CUDA GPUs (A10, V100, etc.) on SURF HPC Cloud.

Parallel to finetune_gysberg_gpu.py but trains on delegate/person mentions.
Uses character-offset-based token labeling for accurate entity recognition.
"""

import os
import sys
import logging
import torch
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from flair.data import Corpus, Sentence, Token
from flair.datasets import SentenceDataset
from flair.embeddings import TransformerWordEmbeddings
from flair.models import SequenceTagger
from flair.trainers import ModelTrainer
from flair.training_utils import EvaluationMetric, AnnealOnPlateau

# ============================================================================
# CONFIGURATION
# ============================================================================

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"\n{'='*70}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU count: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        print(f"  GPU {i}: {torch.cuda.get_device_name(i)}")
    print(f"CUDA version: {torch.version.cuda}")
print(f"PyTorch version: {torch.__version__}")
print(f"{'='*70}\n")

# Set torch to use CUDA
torch.cuda.empty_cache()
if torch.cuda.is_available():
    torch.set_default_device("cuda")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path("data")
MODEL_DIR = Path("models/gysberg_delegate_ner_gpu")
TRAINING_DATA = DATA_DIR / "training_pairs_per_1626_1630_dedup.parquet"

# Training hyperparameters
BATCH_SIZE = 16  # Can be larger with 2 A10 GPUs
MAX_EPOCHS = 15
LEARNING_RATE = 0.1
MAX_SENTENCE_LENGTH = 100  # Words; ~250-300 BERT tokens
WARMUP_EPOCHS = 0
PATIENCE = 3
ANNEAL_FACTOR = 0.5

# ============================================================================
# DATA LOADING & FORMATTING
# ============================================================================

def load_training_data():
    """Load PER training pairs from parquet."""
    logger.info(f"Loading training data from {TRAINING_DATA}")
    df = pd.read_parquet(TRAINING_DATA)
    logger.info(f"Loaded {len(df)} training records")
    return df

def format_sentence_with_labels(group_df):
    """
    Format a group of annotations for one resolution into Flair Sentences.
    Uses CHARACTER OFFSETS to label tokens (fixed from word-matching approach).
    
    Columns:
      - htr_span: the annotated entity text (delegate name)
      - offset: character position in paragraph_texts
      - end: end character position
      - paragraph_texts: full paragraph text
    """
    sentences = []
    
    for para_idx, para_group in group_df.groupby('para_idx'):
        paragraph_text = para_group.iloc[0]['paragraph_texts']
        
        # Tokenize paragraph into words
        words = paragraph_text.split()
        if len(words) > MAX_SENTENCE_LENGTH:
            words = words[:MAX_SENTENCE_LENGTH]
        
        # Reconstruct text from truncated words to get character positions
        truncated_text = ' '.join(words)
        
        # Create Flair Sentence with tokens
        sentence = Sentence(truncated_text)
        
        # Collect NAME spans (character offsets in paragraph_text, not truncated_text)
        name_spans = []
        for _, row in para_group.iterrows():
            offset = row['offset']
            end = row['offset'] + len(row['htr_span'])
            name_spans.append((offset, end))
        
        # Map tokens to character positions in truncated_text
        # We need to align the truncated_text back to the original paragraph
        char_pos = 0
        for token in sentence.tokens:
            token_text = token.text
            
            # Find actual character range in truncated_text
            token_start = truncated_text.find(token_text, char_pos)
            if token_start == -1:
                # Fallback: estimate based on position
                token_start = char_pos
            token_end = token_start + len(token_text)
            
            # Store positions for label matching
            token.start_position = token_start
            token.end_position = token_end
            char_pos = token_end + 1  # +1 for space
            
            # Check if token overlaps with any NAME span
            is_name = False
            for span_start, span_end in name_spans:
                # Check if token overlaps with span
                # (span is in original paragraph, so we use truncated offsets)
                if token_start < span_end and token_end > span_start:
                    is_name = True
                    break
            
            if is_name:
                token.add_label('ner', 'NAME')
            else:
                token.add_label('ner', 'O')
        
        # Only keep sentences with at least one NAME token
        has_name = any(token.get_label('ner').value == 'NAME' for token in sentence.tokens)
        if has_name and len(sentence.tokens) > 0:
            sentences.append(sentence)
    
    return sentences

def create_corpus():
    """
    Create train/dev/test corpus with date-stratified splitting.
    """
    logger.info("Creating corpus...")
    df = load_training_data()
    
    # Parse dates
    df['date_parsed'] = pd.to_datetime(df['date'])
    df = df.sort_values('date_parsed').reset_index(drop=True)
    
    # Date-stratified split: 70% train, 15% dev, 15% test
    n_total = len(df)
    train_end = int(n_total * 0.70)
    dev_end = train_end + int(n_total * 0.15)
    
    df_train = df.iloc[:train_end]
    df_dev = df.iloc[train_end:dev_end]
    df_test = df.iloc[dev_end:]
    
    logger.info(f"Split: train={len(df_train)}, dev={len(df_dev)}, test={len(df_test)}")
    
    # Format sentences with labels
    logger.info("Formatting training sentences...")
    train_sentences = []
    for res_id, group in df_train.groupby('resolution_id'):
        group['para_idx'] = 0  # Add para_idx for compatibility
        train_sentences.extend(format_sentence_with_labels(group))
    
    logger.info("Formatting dev sentences...")
    dev_sentences = []
    for res_id, group in df_dev.groupby('resolution_id'):
        group['para_idx'] = 0
        dev_sentences.extend(format_sentence_with_labels(group))
    
    logger.info("Formatting test sentences...")
    test_sentences = []
    for res_id, group in df_test.groupby('resolution_id'):
        group['para_idx'] = 0
        test_sentences.extend(format_sentence_with_labels(group))
    
    logger.info(f"Corpus: train={len(train_sentences)}, dev={len(dev_sentences)}, test={len(test_sentences)}")
    
    # Create Corpus
    train_dataset = SentenceDataset(train_sentences)
    dev_dataset = SentenceDataset(dev_sentences)
    test_dataset = SentenceDataset(test_sentences)
    
    corpus = Corpus(train=train_dataset, dev=dev_dataset, test=test_dataset)
    logger.info(f"Corpus created: {corpus}")
    
    return corpus

def finetune_model(corpus):
    """
    Fine-tune GysBERT with CRF layer.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize embeddings (Transformer)
    logger.info("Loading GysBERT embeddings...")
    embeddings = TransformerWordEmbeddings(
        model="emanjavacas/GysBERT",
        use_context=True,
        layers="-1",  # Use last layer
        subtoken_pooling="mean",
    )
    
    # Initialize tagger
    logger.info("Creating SequenceTagger...")
    tagger = SequenceTagger(
        embeddings=embeddings,
        tag_type="ner",
        tag_dictionary=corpus.make_tag_dictionary("ner"),
        use_crf=True,
        use_rnn=True,
        rnn_type="LSTM",
        hidden_size=256,
        num_layers=1,
        dropout=0.1,
    )
    
    # Move to GPU
    tagger.to(DEVICE)
    logger.info(f"Model moved to device: {DEVICE}")
    
    # Initialize trainer
    logger.info("Initializing trainer...")
    trainer = ModelTrainer(tagger, corpus)
    
    # Train
    logger.info("Starting training...")
    trainer.train(
        base_path=str(MODEL_DIR),
        learning_rate=LEARNING_RATE,
        mini_batch_size=BATCH_SIZE,
        mini_batch_chunk_size=4,  # Gradient accumulation
        max_epochs=MAX_EPOCHS,
        anneal_with_restarts=False,
        anneal_against_dev_score=True,
        anneal_with_linear_decay=False,
        save_final_model=True,
        save_best_model=True,
        monitor_train=True,
        use_final_model_for_eval=False,
        train_with_dev=False,
        cyclic_schedule_momentum=True,
        patience=PATIENCE,
        anneal_factor=ANNEAL_FACTOR,
        metric=EvaluationMetric.F1,
        use_amp=True,  # Automatic mixed precision for GPU
    )
    
    logger.info(f"Training completed. Model saved to {MODEL_DIR}")

def main():
    """Main training pipeline."""
    logger.info("Starting GysBERT fine-tuning on GPU (DELEGATE model)")
    logger.info(f"Device: {DEVICE}")
    logger.info(f"Config: batch_size={BATCH_SIZE}, max_epochs={MAX_EPOCHS}, lr={LEARNING_RATE}")
    
    # Create corpus
    corpus = create_corpus()
    
    # Fine-tune
    finetune_model(corpus)
    
    logger.info("Fine-tuning complete!")

if __name__ == "__main__":
    main()
