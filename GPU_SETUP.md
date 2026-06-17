# GPU Training Setup Guide: SURF HPC Cloud

## Machine Details
- **Host**: ubuntu2204d1tb.republic-huc-kn.src.surf-hosted.nl
- **IP**: 145.38.187.86
- **SSH URL**: ssh://rhoekstra3@145.38.187.86
- **GPUs**: 2× NVIDIA A10 (24 GB memory each)
- **OS**: Ubuntu 22.04
- **Storage**: 1TB

## Step 1: SSH to the Machine

```bash
ssh rhoekstra3@145.38.187.86
```

Or use the domain:
```bash
ssh rhoekstra3@ubuntu2204d1tb.republic-huc-kn.src.surf-hosted.nl
```

## Step 2: Run Setup Script

Once logged in, run the setup from the machine (OR copy-paste the commands):

```bash
# Option A: Download and run setup script
cd ~
curl -O https://raw.githubusercontent.com/... setup_remote.sh
bash setup_remote.sh

# Option B: Manual setup (copy-paste these commands)
cd ~
python3 -m venv republic_env
source republic_env/bin/activate
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install flair==0.15.0 pandas numpy scikit-learn tqdm
```

Verify PyTorch GPU support:
```bash
python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"
```

## Step 2b: Training Models

You have **two separate NER models** to train (see GPU_TRAINING_WORKFLOW.md for details):

1. **PLACE Model** (`finetune_gysberg_gpu.py`): Recognizes location mentions → for resolution alignment
2. **DELEGATE Model** (`finetune_gysberg_delegate.py`): Recognizes delegate/person names → for delegate searching

Transfer both:
```bash
rsync -avz finetune_gysberg_gpu.py rhoekstra3@145.38.187.86:~/republic_ner_matching/
rsync -avz finetune_gysberg_delegate.py rhoekstra3@145.38.187.86:~/republic_ner_matching/
rsync -avz data/training_pairs_loc_1626_1630_dedup.parquet rhoekstra3@145.38.187.86:~/republic_ner_matching/data/
rsync -avz data/training_pairs_per_1626_1630_dedup.parquet rhoekstra3@145.38.187.86:~/republic_ner_matching/data/
```

## Step 3: Transfer Data from macOS

On your **local machine**, run:

```bash
cd /Users/rikhoekstra/develop/republic_ner_matching

# Create data directory on remote (run once)
ssh rhoekstra3@145.38.187.86 mkdir -p ~/republic_ner_matching/data

# Transfer training data for BOTH models
rsync -avz data/training_pairs_loc_1626_1630_dedup.parquet rhoekstra3@145.38.187.86:~/republic_ner_matching/data/
rsync -avz data/training_pairs_per_1626_1630_dedup.parquet rhoekstra3@145.38.187.86:~/republic_ner_matching/data/

# Transfer both training scripts
rsync -avz finetune_gysberg_gpu.py rhoekstra3@145.38.187.86:~/republic_ner_matching/
rsync -avz finetune_gysberg_delegate.py rhoekstra3@145.38.187.86:~/republic_ner_matching/
```

Verify transfer:
```bash
ssh rhoekstra3@145.38.187.86 "ls -lh ~/republic_ner_matching/data/ && ls -lh ~/republic_ner_matching/*.py"
```

## Step 4: Run Training

SSH back to the machine and run **both models sequentially**:

```bash
ssh rhoekstra3@145.38.187.86
cd ~/republic_ner_matching
source republic_env/bin/activate

# Train PLACE model (for resolution alignment)
echo "=== Training PLACE model ==="
python finetune_gysberg_gpu.py

# Train DELEGATE model (for delegate searching)
echo "=== Training DELEGATE model ==="
python finetune_gysberg_delegate.py
```

Expected runtime: 
- PLACE model: **20-30 minutes** (15 epochs on 21K records)
- DELEGATE model: **15-25 minutes** (15 epochs on 13K records)
- **Total: ~45-55 minutes** for both models

Monitor with:
```bash
watch nvidia-smi  # Shows GPU usage, press Ctrl+C to exit
```

## Step 5: Transfer Results Back

After training completes, copy both models back:

```bash
# On your local machine
mkdir -p models/gysberg_place_ner_gpu models/gysberg_delegate_ner_gpu

rsync -avz rhoekstra3@145.38.187.86:~/republic_ner_matching/models/gysberg_place_ner_gpu/ models/gysberg_place_ner_gpu/
rsync -avz rhoekstra3@145.38.187.86:~/republic_ner_matching/models/gysberg_delegate_ner_gpu/ models/gysberg_delegate_ner_gpu/
```

This retrieves both `best-model.pt` files and training logs.

## File Checklist

**Local files needed for transfer:**
- ✓ `finetune_gysberg_gpu.py` (PLACE model training)
- ✓ `finetune_gysberg_delegate.py` (DELEGATE model training)
- ✓ `data/training_pairs_loc_1626_1630_dedup.parquet` (PLACE training data)
- ✓ `data/training_pairs_per_1626_1630_dedup.parquet` (DELEGATE training data)

**Expected remote files after training:**
```
~/republic_ner_matching/
├── republic_env/                      # Virtual environment
├── finetune_gysberg_gpu.py
├── finetune_gysberg_delegate.py
├── data/
│   ├── training_pairs_loc_1626_1630_dedup.parquet
│   └── training_pairs_per_1626_1630_dedup.parquet
└── models/
    ├── gysberg_place_ner_gpu/         # PLACE model outputs
    │   ├── training.log
    │   ├── best-model.pt
    │   └── final-model.pt
    └── gysberg_delegate_ner_gpu/      # DELEGATE model outputs
        ├── training.log
        ├── best-model.pt
        └── final-model.pt
```

## Troubleshooting

**CUDA not found:**
```bash
# Check CUDA installation
nvidia-smi
```

If nvidia-smi fails, the CUDA drivers aren't installed. Contact SURF support.

**PyTorch can't find CUDA:**
```bash
# Reinstall with correct CUDA version
pip uninstall torch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

**Out of memory on GPU:**
Edit `finetune_gysberg_gpu.py` line ~98:
```python
BATCH_SIZE = 8  # Reduce from 16
```

**SSH connection timeout:**
```bash
# Add persistent connection
ssh -o TCPKeepAlive=yes rhoekstra3@145.38.187.86
```

Or use `screen` to keep session alive:
```bash
screen -S training
python finetune_gysberg_gpu.py
# Detach: Ctrl+A then D
# Reattach: screen -r training
```

## Next: Evaluation

After training, copy the results back and run on your local machine:

```bash
# Create evaluation notebook or script to:
# 1. Load best-model.pt
# 2. Evaluate on test set
# 3. Generate precision/recall/F1 metrics
```

See `evaluation_report.ipynb` for evaluation patterns.
