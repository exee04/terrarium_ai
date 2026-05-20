#!/bin/bash
# Digital Terrarium — Pi Setup Script
# Run once on a fresh Pi to install Ollama and pull all required models.

set -e  # exit on any error

echo "================================"
echo " Digital Terrarium — Pi Setup"
echo "================================"

# ── Ollama ──────────────────────────────────────────────────
echo ""
echo "[1/2] Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# ── Models ──────────────────────────────────────────────────
echo ""
echo "[2/2] Pulling models..."

# Primary text model — personality-driven conversation
ollama pull gemma3:4b

# Vision model — meme/image reactions (load on demand)
ollama pull moondream:1.8b

# Optional: uncomment for a second, snappier text personality
# ollama pull phi3.5:mini

# ── Done ────────────────────────────────────────────────────
echo ""
echo "================================"
echo " Setup complete!"
echo "================================"
ollama list
