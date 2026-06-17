#!/bin/bash
# Install flair dependencies for fine-tuning

echo "Installing GysBERT fine-tuning dependencies..."
echo ""

# Install flair with torch and transformers
echo "[1/3] Installing flair framework..."
uv pip install 'flair>=0.15.0'

echo ""
echo "[2/3] Installing PyTorch (CPU by default)..."
echo "      For GPU support, install manually:"
echo "      uv pip install torch --index-url https://download.pytorch.org/whl/cu121"
uv pip install 'torch>=2.0'

echo ""
echo "[3/3] Installing HuggingFace transformers..."
uv pip install 'transformers>=4.40'

echo ""
echo "✅ Installation complete!"
echo ""
echo "To fine-tune GysBERT on 1626-1630 delegate mentions:"
echo "  uv run python finetune_gysberg.py"
echo ""
