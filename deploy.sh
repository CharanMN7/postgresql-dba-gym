#!/usr/bin/env bash
# Deploy PostgreSQL DBA Gym to a HuggingFace Docker Space.
#
# Prerequisites:
#   pip install huggingface_hub
#   huggingface-cli login    # one-time, token needs write scope
#
# The target Space must already exist and be configured as sdk=docker
# with app_port=8000 (the README.md frontmatter already sets this, so a
# fresh Space created via `huggingface-cli repo create --type space --sdk docker`
# will pick it up on first push).
set -euo pipefail

SPACE_NAME="${SPACE_NAME:-CharanMN7/postgresql-dba-gym}"

echo "==> Deploying to HuggingFace Space: ${SPACE_NAME}"
echo "    Make sure the Space exists and is configured as sdk=docker."
echo ""

if ! command -v huggingface-cli >/dev/null 2>&1; then
    echo "ERROR: huggingface-cli not found. Install with: pip install huggingface_hub" >&2
    exit 1
fi

# Upload everything in the current directory to the Space root, excluding
# local venvs, caches, and the .env (which should never be committed).
huggingface-cli upload "${SPACE_NAME}" . . \
    --repo-type space \
    --exclude ".venv/*" ".venv312/*" "__pycache__/*" "**/__pycache__/*" \
              ".pytest_cache/*" ".mypy_cache/*" ".ruff_cache/*" \
              ".env" ".git/*" "*.pyc"

echo ""
echo "==> Deploy complete."
echo "    Build status: https://huggingface.co/spaces/${SPACE_NAME}"
echo "    Wait for the Space to reach 'Running' before submitting."
