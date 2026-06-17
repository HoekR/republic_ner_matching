#!/bin/bash
#SBATCH --job-name=setup-gysbert
#SBATCH --time=00:45:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1

# Setup script for SURF HPC Cloud machine (INITIAL SETUP on clean remote)
# All data and code stored in /data/storage1tb due to home directory space limits
# 
# WORKFLOW:
# 1. Transfer this script: scp setup_remote.sh user@surfmachine:/data/storage1tb/
# 2. SSH to remote: ssh user@surfmachine
# 3. Submit job: sbatch setup_remote.sh
# 4. After setup completes: transfer data and code files

set -e

echo "=========================================="
echo "INITIAL SETUP: Creating directories and installing packages"
echo "=========================================="
echo "Job started at $(date)"

# Create project directory structure on large storage volume
echo "Creating project directories..."
PROJECT_DIR=/data/storage1tb/republic_ner_matching
PIP_DIR=/data/storage1tb/pip
DATA_DIR=$PROJECT_DIR/data

mkdir -p $PROJECT_DIR
mkdir -p $PIP_DIR/.local
mkdir -p $PIP_DIR/.cache
mkdir -p $DATA_DIR

cd $PROJECT_DIR

echo "Project directory: $PROJECT_DIR"
echo "Pip directory: $PIP_DIR"

# Load CUDA module (typical for SURF HPC)
echo "Loading CUDA module..."
module load CUDA/11.8.0 2>/dev/null || module load cuda 2>/dev/null || echo "  (CUDA module loading skipped)"

# Upgrade pip (install to custom location)
echo "Upgrading pip to custom location..."
python3 -m pip install --upgrade pip setuptools wheel \
  --target $PIP_DIR/.local \
  --cache-dir $PIP_DIR/.cache \
  --no-warn-script-location

# Install core dependencies with custom pip location
echo "Installing PyTorch with CUDA support..."
python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 \
  --target $PIP_DIR/.local \
  --cache-dir $PIP_DIR/.cache \
  --no-warn-script-location

# Install Flair and dependencies
echo "Installing Flair and dependencies..."
python3 -m pip install flair==0.15.0 pandas numpy scikit-learn tqdm pyarrow \
  --target $PIP_DIR/.local \
  --cache-dir $PIP_DIR/.cache \
  --no-warn-script-location

# Create activation script for easy PYTHONPATH setup
cat > $PROJECT_DIR/activate_env.sh << 'EOF'
#!/bin/bash
export PYTHONPATH="/data/storage1tb/pip/.local:$PYTHONPATH"
export PROJECT_DIR="/data/storage1tb/republic_ner_matching"
export DATA_DIR="/data/storage1tb/republic_ner_matching/data"
cd $PROJECT_DIR
echo "✓ Environment activated"
echo "  PYTHONPATH: /data/storage1tb/pip/.local"
echo "  PROJECT_DIR: $PROJECT_DIR"
EOF
chmod +x $PROJECT_DIR/activate_env.sh

echo ""
echo "=========================================="
echo "✓ Environment setup complete!"
echo "=========================================="
echo "Job finished at $(date)"
echo ""
echo "NEXT: Transfer your project files and data"
echo ""
echo "From your local machine, run:"
echo "  1. rsync -av data/*.parquet user@surfmachine:/data/storage1tb/republic_ner_matching/data/"
echo "  2. rsync -av *.py user@surfmachine:/data/storage1tb/republic_ner_matching/"
echo "  3. rsync -av train.slurm user@surfmachine:/data/storage1tb/republic_ner_matching/"
echo ""
echo "Then on the remote machine:"
echo "  1. source /data/storage1tb/republic_ner_matching/activate_env.sh"
echo "  2. sbatch train.slurm"
echo ""
