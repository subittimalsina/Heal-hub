#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OLLAMA_URL="${HEAL_HUB_OLLAMA_URL:-http://127.0.0.1:11434}"
OLLAMA_MODEL="${HEAL_HUB_OLLAMA_MODEL:-qwen2.5:0.5b}"
OLLAMA_TIMEOUT="${HEAL_HUB_OLLAMA_TIMEOUT:-15}"
OLLAMA_NUM_PREDICT="${HEAL_HUB_OLLAMA_NUM_PREDICT:-72}"
SETUP_ONLY="${HEAL_HUB_SETUP_ONLY:-0}"
OLLAMA_LOG="${ROOT_DIR}/.ollama.log"

log() {
  printf '\n[Heal Hub] %s\n' "$1"
}

fail() {
  printf '\n[Heal Hub] Error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || fail "Missing required command: ${command_name}"
}

ollama_ready() {
  curl -fsS "${OLLAMA_URL%/}/api/version" >/dev/null 2>&1
}

start_ollama_service() {
  if ollama_ready; then
    return 0
  fi

  log "Starting Ollama service..."
  nohup ollama serve >"${OLLAMA_LOG}" 2>&1 &

  for _ in $(seq 1 30); do
    sleep 1
    if ollama_ready; then
      return 0
    fi
  done

  fail "Ollama did not become ready. Check ${OLLAMA_LOG} for details."
}

write_local_env() {
  cat > "${ROOT_DIR}/.env.local" <<EOF
HEAL_HUB_AI_BACKEND=ollama
HEAL_HUB_OLLAMA_URL=${OLLAMA_URL%/}
HEAL_HUB_OLLAMA_MODEL=${OLLAMA_MODEL}
HEAL_HUB_OLLAMA_TIMEOUT=${OLLAMA_TIMEOUT}
HEAL_HUB_OLLAMA_NUM_PREDICT=${OLLAMA_NUM_PREDICT}
EOF
}

log "Preparing Heal Hub in ${ROOT_DIR}"
require_command "${PYTHON_BIN}"
require_command curl

if [[ ! -d "${VENV_DIR}" ]]; then
  log "Creating Python virtual environment..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

log "Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install -r "${ROOT_DIR}/requirements.txt"

if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

command -v ollama >/dev/null 2>&1 || fail "Ollama installation failed or is not on PATH."

start_ollama_service

log "Pulling local model ${OLLAMA_MODEL}..."
ollama pull "${OLLAMA_MODEL}"

write_local_env
log "Saved local AI config to .env.local"

if [[ "${SETUP_ONLY}" == "1" ]]; then
  log "Setup complete. Start the app later with: ./.venv/bin/python app.py"
  exit 0
fi

log "Starting Heal Hub on http://127.0.0.1:5000"
cd "${ROOT_DIR}"
exec "${VENV_DIR}/bin/python" app.py
