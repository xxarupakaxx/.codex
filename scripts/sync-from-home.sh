#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
codex_home="${CODEX_HOME:-${HOME}/.codex}"

if [ -d "${codex_home}" ]; then
  python3 "${repo_root}/scripts/normalize-codex-models.py" "${codex_home}"
  python3 "${repo_root}/scripts/verify-codex-model-compat.py" "${codex_home}"
fi

python3 "${repo_root}/scripts/normalize-codex-models.py" "${repo_root}"
python3 "${repo_root}/scripts/verify-codex-model-compat.py" "${repo_root}"
git -C "${repo_root}" status --short
