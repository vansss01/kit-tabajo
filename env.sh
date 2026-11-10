# Uso desde Bash: source ./env.sh
KIT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export TMPDIR="$KIT_ROOT/tmp" TEMP="$KIT_ROOT/tmp" TMP="$KIT_ROOT/tmp"
export XDG_CACHE_HOME="$KIT_ROOT/.cache" XDG_CONFIG_HOME="$KIT_ROOT/.runtime/config"
export XDG_DATA_HOME="$KIT_ROOT/.runtime/data" XDG_STATE_HOME="$KIT_ROOT/.runtime/state"
export PIP_CACHE_DIR="$KIT_ROOT/.cache/pip" RUFF_CACHE_DIR="$KIT_ROOT/.cache/ruff"
export MYPY_CACHE_DIR="$KIT_ROOT/.cache/mypy" PYTHONDONTWRITEBYTECODE=1
export PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1
source "$KIT_ROOT/.venv/bin/activate"
