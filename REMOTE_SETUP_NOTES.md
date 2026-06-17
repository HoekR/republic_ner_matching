# Remote SURF Machine Setup Notes

## Environment Details
- **Machine**: SURF HPC Cloud (145.38.187.86)
- **User**: rhoekstra3
- **Storage**: /data/storage1tb (1TB volume for all code/data)
- **Python**: 3.x
- **Kernel**: 5.15.0-168-generic

## Issues Encountered & Solutions

### Issue 1: Home Directory Space Limitations
**Problem**: Home directory doesn't have enough space for packages or large datasets

**Solution**: 
- All code and data stored in `/data/storage1tb`
- Packages installed with custom `--target` and `--cache-dir`:
```bash
python3 -m pip install <package> \
  --target /data/storage1tb/pip/.local \
  --cache-dir /data/storage1tb/pip/.cache
```
- Must set `PYTHONPATH` to find packages:
```bash
export PYTHONPATH="/data/storage1tb/pip/.local:$PYTHONPATH"
```

### Issue 2: SBATCH Not Available
**Problem**: Remote machine doesn't have SLURM installed

**Solution**: 
- Run setup scripts directly instead of using `sbatch`
- Modified `deploy.sh` to execute setup script with SSH instead of `sbatch`
- Training can still use SLURM if installed later (scripts remain compatible)

### Issue 3: Missing Parquet Support
**Problem**: `ImportError: Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'`

**Solution**:
- Install `pyarrow`: 
```bash
python3 -m pip install pyarrow --target /data/storage1tb/pip/.local --cache-dir /data/storage1tb/pip/.cache
```

### Issue 4: CUDA/GPU Setup
**Status**: ⚠️ NVIDIA driver not working, but toolkit installed

**Details**:
- `nvcc` exists: `/usr/bin/nvcc`
- `nvidia-smi` fails: "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver"
- `modprobe nvidia` fails: "Module nvidia not found in directory /lib/modules/5.15.0-168-generic"
- **Root cause**: NVIDIA drivers not installed for kernel `5.15.0-168-generic`

**Current Workaround**:
- Training runs on CPU (slower but functional)
- PyTorch installed with CUDA support (`cu118`):
```bash
python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 \
  --target /data/storage1tb/pip/.local \
  --cache-dir /data/storage1tb/pip/.cache \
  --no-warn-script-location --upgrade
```
- Check status: `python3 -c "import torch; print('CUDA available:', torch.cuda.is_available())"`

**Expected Speed Impact**:
- CPU training: ~5-10x slower than GPU
- For 1.25M LOC pairs + 1.38M PER pairs, expect training to take hours per epoch

**How to Enable GPU Later**:
1. SURF admins need to install NVIDIA drivers for the kernel
2. Once driver is fixed, CUDA will automatically be available
3. No code changes needed - PyTorch will automatically use GPU

## Activation Script
After setup, use this to activate environment:
```bash
source /data/storage1tb/republic_ner_matching/activate_env.sh
```

This sets:
- `PYTHONPATH=/data/storage1tb/pip/.local`
- `PROJECT_DIR=/data/storage1tb/republic_ner_matching`
- `DATA_DIR=/data/storage1tb/republic_ner_matching/data`

## Quick Reference

### Deploy from local machine
```bash
bash deploy.sh
```

### SSH to remote
```bash
ssh rhoekstra3@145.38.187.86
source /data/storage1tb/republic_ner_matching/activate_env.sh
```

### Run training (CPU)
```bash
python finetune_gysberg_gpu.py
```

### Run training (GPU - once driver fixed)
```bash
python finetune_gysberg_gpu.py
# (same command, will automatically use GPU)
```

### Check CUDA status
```bash
python3 -c "import torch; print('CUDA:', torch.cuda.is_available()); print('Version:', torch.version.cuda)"
```

### Manually install missing packages
```bash
python3 -m pip install <package> \
  --target /data/storage1tb/pip/.local \
  --cache-dir /data/storage1tb/pip/.cache
```

## Admin Actions Needed
- Install NVIDIA drivers for kernel `5.15.0-168-generic`
- This will enable GPU support without any code changes

## Data & Scripts
- **Location**: `/data/storage1tb/republic_ner_matching/`
- **Data**: `data/*.parquet` (LOC and PER training pairs)
- **Training scripts**: `finetune_gysberg_gpu.py`, `finetune_gysberg_delegate_local.py`
- **Environment setup**: `setup_remote.sh`, `activate_env.sh`
- **Deployment**: `deploy.sh` (run locally)

