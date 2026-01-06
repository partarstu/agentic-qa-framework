#!/bin/bash
# ============================================================================
# Orchestrator Dashboard UI - Build and Start
# ============================================================================
# This script builds the React UI for production and copies it to the
# orchestrator/static folder, then starts the orchestrator backend.
# 
# The dashboard will be available at http://localhost:8080/
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/../.."
STATIC_DIR="${SCRIPT_DIR}/../static"

cd "$SCRIPT_DIR"

echo ""
echo "============================================"
echo "  Orchestrator Dashboard UI"
echo "============================================"
echo ""

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "[1/4] Installing dependencies..."
    npm install
else
    echo "[1/4] Dependencies already installed."
fi

echo "[2/4] Building production bundle..."
npm run build

echo "[3/4] Copying to orchestrator/static..."

# Remove old static files
rm -rf "$STATIC_DIR"

# Copy new build
mkdir -p "$STATIC_DIR"
cp -r dist/* "$STATIC_DIR/"

echo "[4/4] Starting orchestrator..."
echo ""
echo "============================================"
echo "  Dashboard ready at http://localhost:8080"
echo "============================================"
echo ""
echo "Press Ctrl+C to stop the server."
echo ""

cd "$PROJECT_ROOT"
python -m uvicorn orchestrator.main:orchestrator_app --host 0.0.0.0 --port 8080 --reload
