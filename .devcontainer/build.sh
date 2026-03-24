#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[bootstrap] $*"
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BREWFILE="${BREWFILE:-$REPO_ROOT/.devcontainer/Brewfile}"

# Install system dependencies
if command -v apt-get >/dev/null 2>&1; then
  log "Installing system packages via apt-get"
  sudo apt-get update -y
  sudo apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0
fi

# Install Homebrew packages
if command -v brew >/dev/null 2>&1; then
  if [ -d /home/linuxbrew/.linuxbrew ]; then
    sudo chown -R "$(id -u)":"$(id -g)" /home/linuxbrew/.linuxbrew || true
  fi
  if [ -f "$BREWFILE" ]; then
    log "Running brew bundle install"
    brew bundle install --file "$BREWFILE" || true
  fi
fi

# Setup Python environment with uv
if command -v uv >/dev/null 2>&1; then
  log "Setting up Python environment with uv"
  cd "$REPO_ROOT"
  uv venv --system-site-packages
  uv sync
else
  log "uv not found, skipping Python setup"
fi

log "Build complete"
