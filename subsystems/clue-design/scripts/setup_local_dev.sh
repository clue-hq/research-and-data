#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDITOR_DIR="$ROOT_DIR/apps/editor"
CUSTOM_COMPONENT_COMPILER_DIR="$ROOT_DIR/apps/custom-component-compiler"
API_DIR="$ROOT_DIR/apps/api"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN=""
START_AFTER_SETUP=0

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/setup_local_dev.sh
  ./scripts/setup_local_dev.sh --start

What it does:
  - Installs missing macOS prerequisites with Homebrew where possible.
  - Creates a Python virtual environment at ./.venv.
  - Installs FastAPI/agent runtime Python packages.
  - Installs editor Node packages.
  - Builds/checks the Rust design-engine helper.
  - Creates .env from .env.example if .env is missing.

Options:
  --start    Start the API and editor dev servers after setup.
  -h, --help Show this help.
USAGE
}

log() {
  printf "\033[1;34m==>\033[0m %s\n" "$1"
}

warn() {
  printf "\033[1;33mWarning:\033[0m %s\n" "$1"
}

fail() {
  printf "\033[1;31mError:\033[0m %s\n" "$1" >&2
  exit 1
}

is_macos() {
  [[ "$(uname -s)" == "Darwin" ]]
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi

  is_macos || fail "Homebrew auto-install is supported only on macOS. Install missing dependencies manually, then rerun this script."

  log "Homebrew is not installed. Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi

  command -v brew >/dev/null 2>&1 || fail "Homebrew install finished, but brew is still not on PATH. Open a new terminal and rerun this script."
}

install_with_brew_if_missing() {
  local command_name="$1"
  local formula="$2"
  local display_name="$3"

  if command -v "$command_name" >/dev/null 2>&1; then
    log "$display_name found: $("$command_name" --version 2>/dev/null | head -n 1 || printf "installed")"
    return
  fi

  is_macos || fail "$display_name is missing. Automatic installation is only supported on macOS."
  ensure_homebrew
  log "$display_name is missing. Installing $formula with Homebrew..."
  brew install "$formula"
  command -v "$command_name" >/dev/null 2>&1 || fail "$display_name installation did not put $command_name on PATH."
}

find_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local candidate_path
      candidate_path="$(command -v "$candidate")"
      if "$candidate_path" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(1)
PY
      then
        PYTHON_BIN="$candidate_path"
        log "Python found: $("$PYTHON_BIN" --version)"
        return
      fi
      warn "$candidate_path is older than Python 3.11."
    fi
  done

  is_macos || fail "Python 3.11 or newer is required. Install it manually, then rerun this script."
  ensure_homebrew
  log "Installing a current Python with Homebrew..."
  brew install python
  PYTHON_BIN="$(command -v python3)"
  "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required.")
PY
  log "Python found: $("$PYTHON_BIN" --version)"
}

install_python_if_needed() {
  find_python
}

ensure_env_file() {
  if [[ ! -f "$ROOT_DIR/.env" && -f "$ROOT_DIR/.env.example" ]]; then
    log "Creating .env from .env.example"
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    warn "Edit .env and add API keys before using live agent calls."
  elif [[ -f "$ROOT_DIR/.env" ]]; then
    log ".env already exists; leaving it unchanged."
  else
    warn ".env.example is missing; skipping .env creation."
  fi
}

setup_python() {
  install_python_if_needed

  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating Python virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  else
    log "Python virtual environment already exists at $VENV_DIR"
  fi

  local venv_python="$VENV_DIR/bin/python"
  [[ -x "$venv_python" ]] || fail "Virtual environment Python was not found at $venv_python"

  log "Upgrading pip"
  "$venv_python" -m pip install --upgrade pip

  log "Installing API and agent runtime Python packages"
  "$venv_python" -m pip install -r "$API_DIR/requirements-dev.txt"
}

setup_node() {
  install_with_brew_if_missing node node "Node.js"
  install_with_brew_if_missing npm node "npm"
  local node_major
  node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
  if (( node_major < 24 )); then
    fail "Node.js 24 or newer is required by the constrained custom-component compiler (found $(node --version))."
  fi

  log "Installing editor Node packages"
  if [[ -f "$EDITOR_DIR/package-lock.json" ]]; then
    npm --prefix "$EDITOR_DIR" ci
  else
    npm --prefix "$EDITOR_DIR" install
  fi

  log "Installing custom-component compiler Node packages"
  npm --prefix "$CUSTOM_COMPONENT_COMPILER_DIR" ci
}

setup_print_tools() {
  # Print W5 stage B: CMYK PDF export shells out to Ghostscript on the
  # server side (color:"cmyk" on print-intent profiles). Exports without
  # it fail loudly with export.cmyk_unavailable.
  install_with_brew_if_missing gs ghostscript "Ghostscript"
}

setup_rust() {
  if ! command -v cargo >/dev/null 2>&1 || ! command -v rustc >/dev/null 2>&1; then
    is_macos || fail "Rust is missing. Automatic Rust installation is only supported on macOS."
    ensure_homebrew
    log "Rust is missing. Installing rust with Homebrew..."
    brew install rust
  fi

  command -v cargo >/dev/null 2>&1 || fail "cargo is still missing after Rust installation."
  command -v rustc >/dev/null 2>&1 || fail "rustc is still missing after Rust installation."

  log "Rust found: $(rustc --version)"
  log "Building Rust API helper/design engine"
  cargo build -p lumen-api-helper
}

verify_setup() {
  log "Running quick verification"
  "$VENV_DIR/bin/python" -m pytest "$API_DIR/tests" -q
  npm --prefix "$CUSTOM_COMPONENT_COMPILER_DIR" test
  npm --prefix "$EDITOR_DIR" run lint
  cargo check -p lumen-api-helper
}

print_next_steps() {
  cat <<EOF

Setup complete.

To start the backend API:
  cd "$ROOT_DIR"
  set -a; source .env; set +a
  PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m uvicorn lumen_api.main:app --host 127.0.0.1 --port 8000

To start the frontend editor in another terminal:
  cd "$ROOT_DIR"
  NEXT_PUBLIC_LUMEN_API_BASE_URL=http://127.0.0.1:8000 npm --prefix apps/editor run dev -- --hostname 127.0.0.1 --port 3000

Then open:
  http://127.0.0.1:3000

EOF
}

start_servers() {
  log "Starting backend and frontend dev servers"
  log "Backend: http://127.0.0.1:8000"
  log "Frontend: http://127.0.0.1:3000"
  log "Press Ctrl+C to stop both servers."

  (
    cd "$ROOT_DIR"
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
    PYTHONPATH=.:apps/api:apps/agent_runtime "$VENV_DIR/bin/python" -m uvicorn lumen_api.main:app --host 127.0.0.1 --port 8000
  ) &
  local api_pid=$!

  (
    cd "$ROOT_DIR"
    NEXT_PUBLIC_LUMEN_API_BASE_URL=http://127.0.0.1:8000 npm --prefix apps/editor run dev -- --hostname 127.0.0.1 --port 3000
  ) &
  local editor_pid=$!

  trap 'kill "$api_pid" "$editor_pid" 2>/dev/null || true' INT TERM EXIT
  wait "$api_pid" "$editor_pid"
}

for arg in "$@"; do
  case "$arg" in
    --start)
      START_AFTER_SETUP=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      fail "Unknown option: $arg"
      ;;
  esac
done

cd "$ROOT_DIR"
log "Setting up Lumen design engine at $ROOT_DIR"

ensure_env_file
setup_python
setup_node
setup_print_tools
setup_rust
verify_setup
print_next_steps

if [[ "$START_AFTER_SETUP" == "1" ]]; then
  start_servers
fi
