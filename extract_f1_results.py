#!/usr/bin/env python3
"""
Extract final F1 score from training results
"""
import json
from pathlib import Path

# Look for training results
model_dir = Path("models/gysberg_place_ner")
if not model_dir.exists():
    print("Model directory not found")
    exit(1)

# Check if best-model.pt exists
best_model = model_dir / "best-model.pt"
if best_model.exists():
    print(f"✓ Best model found: {best_model}")
    print(f"  Size: {best_model.stat().st_size / 1024 / 1024:.1f} MB")
else:
    print("✗ Best model not found yet - training still in progress")

# Try to find results.json or training log
for results_file in [model_dir / "results.json", model_dir / "training.log"]:
    if results_file.exists():
        print(f"\nFound: {results_file}")
        if results_file.suffix == ".json":
            with open(results_file) as f:
                data = json.load(f)
                print(json.dumps(data, indent=2))
        else:
            with open(results_file) as f:
                print(f.read()[-500:])
        break

# Check for losses.tsv which contains per-epoch metrics
losses_file = model_dir / "losses.tsv"
if losses_file.exists():
    print(f"\nTraining metrics (losses.tsv):")
    with open(losses_file) as f:
        lines = f.readlines()
        print("".join(lines[-10:]))  # Last 10 lines
