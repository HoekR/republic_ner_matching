#!/bin/zsh
# Deployment script - automates setup and transfer to SURF machine
# Uses credentials from credentials.txt

set -e

echo "=========================================="
echo "Deploying to SURF machine"
echo "=========================================="

# Read credentials
if [ ! -f credentials.txt ]; then
    echo "Error: credentials.txt not found"
    exit 1
fi

REMOTE=$(cat credentials.txt | grep -v '^#' | tr -d ' ')
if [ -z "$REMOTE" ]; then
    echo "Error: No credentials found in credentials.txt"
    exit 1
fi

echo "Remote: $REMOTE"
echo ""

# Step 1: Transfer setup script
echo "Step 1: Transferring setup script..."
scp setup_remote.sh $REMOTE:/data/storage1tb/
echo "  ✓ setup_remote.sh transferred"

# Step 2: Run setup on remote
echo ""
echo "Step 2: Running setup on remote machine..."
ssh $REMOTE "chmod +x /data/storage1tb/setup_remote.sh && /data/storage1tb/setup_remote.sh"
echo "  ✓ Setup completed"

# Step 3: Transfer data
echo ""
echo "Step 3: Transferring data..."
rsync -av --progress data/*.parquet $REMOTE:/data/storage1tb/republic_ner_matching/data/
echo "  ✓ Parquets transferred"

# Step 4: Transfer code
echo ""
echo "Step 4: Transferring code..."
rsync -av --progress *.py train.slurm $REMOTE:/data/storage1tb/republic_ner_matching/
echo "  ✓ Code transferred"

echo ""
echo "=========================================="
echo "✓ Deployment complete!"
echo "=========================================="
echo ""
echo "Next: SSH to remote and start training"
echo "  ssh $REMOTE"
echo "  source /data/storage1tb/republic_ner_matching/activate_env.sh"
echo "  sbatch train.slurm"
echo ""
