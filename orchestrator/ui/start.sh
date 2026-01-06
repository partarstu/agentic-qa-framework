#!/bin/bash
# ============================================================================
# Orchestrator Dashboard UI - Build and Start
# ============================================================================
# This script installs dependencies (if needed), builds the React UI,
# copies it to orchestrator/static, and starts the development server.
# 
# The UI dev server will be available at http://localhost:5173/
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_DIR="${SCRIPT_DIR}/../static"

cd "$SCRIPT_DIR"

echo ""
echo "============================================"
echo "  Orchestrator Dashboard UI"
echo "============================================"
echo ""

# Check required environment variable
if [ -z "$ORCHESTRATOR_PORT" ]; then
    echo "ERROR: ORCHESTRATOR_PORT environment variable is not set."
    echo "Please set it to the port number your orchestrator is running on."
    echo "Example: export ORCHESTRATOR_PORT=8080"
    exit 1
fi

echo "Configured Orchestrator Port: $ORCHESTRATOR_PORT"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "[1/3] Installing dependencies..."
    npm install
else
    echo "[1/3] Dependencies already installed."
fi

echo "[2/3] Building production bundle..."
npm run build

echo "[3/3] Copying to orchestrator/static..."

# Remove old static files
rm -rf "$STATIC_DIR"

# Copy new build
mkdir -p "$STATIC_DIR"
cp -r dist/* "$STATIC_DIR/"

echo ""
echo "============================================"
echo "  Starting UI Development Server"
echo "============================================"
echo ""
echo "UI will be available at: http://localhost:5173"
echo "API calls will be proxied to: http://localhost:$ORCHESTRATOR_PORT"
echo ""
echo "Note: The orchestrator must be running separately on port $ORCHESTRATOR_PORT"
echo ""
echo "Press Ctrl+C to stop the server."
echo ""

npm run dev
