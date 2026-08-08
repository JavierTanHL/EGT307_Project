#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="$ROOT/models/component_classifier.keras"

if [[ ! -f "$MODEL" ]]; then
  echo "ERROR: Model missing: $MODEL"
  echo "Run the notebook and copy component_classifier.keras into models/."
  exit 1
fi

cd "$ROOT"
docker compose up --build
