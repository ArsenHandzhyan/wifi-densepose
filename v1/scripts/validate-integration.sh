#!/bin/bash

# WiFi-DensePose Integration Validation Script
# Validates the current canonical runtime surface for the v1 application.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$APP_ROOT")"
TEST_DB_PATH="${APP_ROOT}/test_integration.db"
LOG_FILE="${APP_ROOT}/integration_validation.log"
REPORT_FILE="${APP_ROOT}/integration_report.md"
UVICORN_LOG="/tmp/wdp_validate_uvicorn.log"
SERVER_PID=""
PYTHON_BIN=""
PACKAGING_STATUS="SKIPPED"
PACKAGING_NOTE="Packaging smoke skipped because build/twine are not installed in the active environment."

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}✅ $1${NC}" | tee -a "$LOG_FILE"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a "$LOG_FILE"
}

cleanup() {
    log "Cleaning up validation resources..."

    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        SERVER_PID=""
    fi

    [ -f "$TEST_DB_PATH" ] && rm -f "$TEST_DB_PATH"
    rm -f "$UVICORN_LOG" /tmp/wdp_validate_health.out /tmp/wdp_validate_endpoint.out

    success "Cleanup completed"
}

resolve_python_bin() {
    local candidates=(
        "${REPO_ROOT}/venv/bin/python"
        "${REPO_ROOT}/.venv/bin/python"
        "${APP_ROOT}/.venv/bin/python"
    )

    for candidate in "${candidates[@]}"; do
        if [ -x "$candidate" ]; then
            PYTHON_BIN="$candidate"
            return
        fi
    done

    PYTHON_BIN="$(command -v python3)"
}

activate_virtualenv() {
    local venv_root=""

    if [[ "$PYTHON_BIN" == */bin/python ]]; then
        venv_root="$(dirname "$(dirname "$PYTHON_BIN")")"
        if [ -f "${venv_root}/bin/activate" ]; then
            # shellcheck disable=SC1090
            source "${venv_root}/bin/activate"
        fi
    fi
}

set_validation_env() {
    export ENVIRONMENT="${ENVIRONMENT:-development}"
    export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///test_integration.db}"
    export SQLITE_FALLBACK_PATH="${SQLITE_FALLBACK_PATH:-./test_integration.db}"
    export REDIS_ENABLED="${REDIS_ENABLED:-false}"
    export REDIS_REQUIRED="${REDIS_REQUIRED:-false}"
    export SECRET_KEY="${SECRET_KEY:-test-secret-key-for-validation-only}"
    export WIFI_DENSEPOSE_ALLOW_MULTI_BACKEND="${WIFI_DENSEPOSE_ALLOW_MULTI_BACKEND:-1}"
}

check_prerequisites() {
    log "Checking prerequisites..."

    resolve_python_bin
    activate_virtualenv
    set_validation_env

    if ! "$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 9):
    raise SystemExit(1)

print("Python", sys.version.split()[0])
PY
    then
        error "Python 3.9+ is required"
        exit 1
    fi
    success "Python version check passed"

    if ! "$PYTHON_BIN" - <<'PY'
import click
import fastapi
import pytest
import uvicorn
PY
    then
        error "Missing required validation dependencies (click, fastapi, pytest, uvicorn)"
        exit 1
    fi
    success "Dependencies check passed"
}

validate_package_structure() {
    log "Validating package structure..."

    local app_required_files=(
        "src/__init__.py"
        "src/main.py"
        "src/app.py"
        "src/config/settings.py"
        "src/logger.py"
        "src/cli.py"
    )

    for file in "${app_required_files[@]}"; do
        if [ ! -f "${APP_ROOT}/${file}" ]; then
            error "Required file missing: $file"
            exit 1
        fi
    done

    if [ ! -f "${REPO_ROOT}/pyproject.toml" ]; then
        error "Required file missing: pyproject.toml"
        exit 1
    fi
    success "Package structure validation passed"

    local required_dirs=(
        "src/config"
        "src/core"
        "src/api"
        "src/services"
        "src/database"
        "src/tasks"
        "src/commands"
        "tests/unit"
        "tests/legacy"
    )

    for dir in "${required_dirs[@]}"; do
        if [ ! -d "${APP_ROOT}/${dir}" ]; then
            error "Required directory missing: $dir"
            exit 1
        fi
    done
    success "Directory structure validation passed"
}

validate_imports() {
    log "Validating Python imports..."

    cd "$APP_ROOT"

    if ! "$PYTHON_BIN" -c "import src; print(f'Package version: {src.__version__}')"; then
        error "Failed to import main package"
        exit 1
    fi
    success "Main package import passed"

    local core_modules=(
        "src.app"
        "src.config.settings"
        "src.logger"
        "src.cli"
        "src.core.csi_processor"
        "src.core.phase_sanitizer"
        "src.core.router_interface"
        "src.services.orchestrator"
        "src.database.connection"
        "src.database.models"
    )

    for module in "${core_modules[@]}"; do
        if ! "$PYTHON_BIN" -c "import $module" 2>/dev/null; then
            error "Failed to import module: $module"
            exit 1
        fi
    done
    success "Core modules import passed"
}

validate_configuration() {
    log "Validating configuration..."

    cd "$APP_ROOT"

    if ! "$PYTHON_BIN" - <<'PY'
from src.config.settings import get_settings

settings = get_settings()
print(f'Environment: {settings.environment}')
print(f'Debug: {settings.debug}')
print(f'Version: {settings.version}')
print(f'API Prefix: {settings.api_prefix}')
print(f'Redis Enabled: {settings.redis_enabled}')
assert settings.secret_key, 'Secret key must be set for validation'
PY
    then
        error "Configuration validation failed"
        exit 1
    fi
    success "Configuration validation passed"
}

validate_database() {
    log "Validating database integration..."

    cd "$APP_ROOT"

    if ! "$PYTHON_BIN" - <<'PY'
import asyncio
from src.config.settings import get_settings
from src.database.connection import get_database_manager

async def test_db():
    settings = get_settings()
    db_manager = get_database_manager(settings)
    await db_manager.initialize()
    assert await db_manager.test_connection(), 'Database test_connection() returned False'
    stats = await db_manager.get_connection_stats()
    print(f'Stats keys: {sorted(stats.keys())}')
    assert 'postgresql' in stats, 'Connection stats missing pool information'
    await db_manager.close_connections()
    print('Database validation passed')

asyncio.run(test_db())
PY
    then
        error "Database validation failed"
        exit 1
    fi
    success "Database validation passed"
}

validate_route_surface() {
    log "Validating API route surface..."

    cd "$APP_ROOT"

    if ! "$PYTHON_BIN" - <<'PY'
from src.app import app

paths = {route.path for route in app.routes}
expected = {
    '/health/health',
    '/api/v1/status',
    '/api/v1/pose/current',
    '/api/v1/csi/status',
    '/api/v1/csi/record/status',
    '/api/v1/fp2/status',
}

missing = sorted(expected - paths)
assert not missing, f'Missing expected routes: {missing}'
print(f'Route count: {len(paths)}')
PY
    then
        error "API route surface validation failed"
        exit 1
    fi
    success "API route surface validation passed"
}

validate_api_endpoints() {
    log "Validating HTTP smoke endpoints..."

    cd "$APP_ROOT"

    "$PYTHON_BIN" -m uvicorn src.app:app --host 127.0.0.1 --port 8888 --log-level error >"$UVICORN_LOG" 2>&1 &
    SERVER_PID=$!

    local ready=0
    local code=""
    local endpoints=(
        "/health/health"
        "/api/v1/status"
        "/api/v1/csi/status"
        "/api/v1/csi/record/status"
        "/api/v1/fp2/status"
    )

    for _ in {1..20}; do
        code="$(curl -s -o /tmp/wdp_validate_health.out -w '%{http_code}' http://127.0.0.1:8888/health/health || true)"
        if [ "$code" = "200" ]; then
            ready=1
            break
        fi
        sleep 1
    done

    if [ "$ready" -ne 1 ]; then
        error "Validation server did not become ready on :8888"
        [ -f "$UVICORN_LOG" ] && sed -n '1,160p' "$UVICORN_LOG" | tee -a "$LOG_FILE"
        exit 1
    fi

    for endpoint in "${endpoints[@]}"; do
        code="$(curl -s -o /tmp/wdp_validate_endpoint.out -w '%{http_code}' "http://127.0.0.1:8888${endpoint}" || true)"
        if [ "$code" != "200" ]; then
            error "HTTP smoke failed: ${endpoint} returned ${code}"
            [ -f /tmp/wdp_validate_endpoint.out ] && sed -n '1,40p' /tmp/wdp_validate_endpoint.out | tee -a "$LOG_FILE"
            exit 1
        fi
    done

    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""

    success "HTTP smoke endpoints validation passed"
}

validate_cli() {
    log "Validating CLI interface..."

    cd "$APP_ROOT"

    if ! "$PYTHON_BIN" -m src.cli --help > /dev/null; then
        error "CLI help command failed"
        exit 1
    fi
    success "CLI help command passed"

    if ! "$PYTHON_BIN" -m src.cli version > /dev/null; then
        error "CLI version command failed"
        exit 1
    fi
    success "CLI version command passed"

    if ! "$PYTHON_BIN" -m src.cli config validate > /dev/null; then
        error "CLI config validation failed"
        exit 1
    fi
    success "CLI config validation passed"
}

validate_background_tasks() {
    log "Validating background tasks..."

    cd "$APP_ROOT"

    if ! "$PYTHON_BIN" - <<'PY'
from src.config.settings import get_settings
from src.tasks.backup import get_backup_manager
from src.tasks.cleanup import get_cleanup_manager
from src.tasks.monitoring import get_monitoring_manager

settings = get_settings()
managers = [
    ('cleanup', get_cleanup_manager),
    ('monitoring', get_monitoring_manager),
    ('backup', get_backup_manager),
]

for name, factory in managers:
    stats = factory(settings).get_stats()
    assert 'manager' in stats, f'{name} manager stats missing manager section'
    print(f'{name}_tasks={len(stats.get("tasks", []))}')

print('Background tasks validation passed')
PY
    then
        error "Background tasks validation failed"
        exit 1
    fi
    success "Background tasks validation passed"
}

run_canonical_test_surface() {
    log "Running canonical pytest surface..."

    cd "$REPO_ROOT"

    if ! "$PYTHON_BIN" -m pytest -q; then
        error "Canonical pytest surface failed"
        exit 1
    fi
    success "Canonical pytest surface passed"
}

validate_package_build() {
    log "Validating package build..."

    cd "$REPO_ROOT"

    if ! "$PYTHON_BIN" - <<'PY' > /dev/null 2>&1
import build
import twine
PY
    then
        warning "$PACKAGING_NOTE"
        return
    fi

    if ! "$PYTHON_BIN" -m build; then
        error "Package build failed"
        exit 1
    fi
    success "Package build passed"

    if ! "$PYTHON_BIN" -m twine check dist/*; then
        error "Package check failed"
        exit 1
    fi
    success "Package check passed"

    rm -rf build/ dist/ *.egg-info/
    PACKAGING_STATUS="PASSED"
    PACKAGING_NOTE="Build and twine metadata checks passed."
}

generate_report() {
    log "Generating integration report..."

    cat > "$REPORT_FILE" <<EOF
# WiFi-DensePose Integration Validation Report

**Date:** $(date)
**Status:** ✅ PASSED

## Validation Results

### Prerequisites
- ✅ Python version check
- ✅ Runtime dependencies present

### Package Structure
- ✅ Required files present
- ✅ Directory structure valid
- ✅ Python imports working

### Core Components
- ✅ Configuration management
- ✅ Database integration
- ✅ API route surface
- ✅ HTTP smoke endpoints
- ✅ CLI interface
- ✅ Background tasks

### Testing
- ✅ Canonical pytest surface passed
- ℹ️ Legacy integration suite remains in \`v1/tests/legacy/integration\` and is not part of default validation
- ${PACKAGING_STATUS} Packaging smoke

### Validation Environment
- Environment: \`${ENVIRONMENT}\`
- Database URL: \`${DATABASE_URL}\`
- SQLite fallback path: \`${SQLITE_FALLBACK_PATH}\`
- Redis enabled: \`${REDIS_ENABLED}\`
- Multi-backend bypass: \`${WIFI_DENSEPOSE_ALLOW_MULTI_BACKEND}\`

## System Information

**Python Version:** $("$PYTHON_BIN" --version)
**Package Version:** $(cd "$APP_ROOT" && "$PYTHON_BIN" -c "import src; print(src.__version__)")
**Environment:** $(cd "$APP_ROOT" && "$PYTHON_BIN" -c "from src.config.settings import get_settings; print(get_settings().environment)")

## Next Steps

The WiFi-DensePose canonical validation surface passed with the current repository layout.
You can now:

1. Start the server: \`cd v1 && uvicorn src.app:app --host 127.0.0.1 --port 8000\`
2. Check status: \`wifi-densepose status\`
3. View configuration: \`wifi-densepose config show\`
4. Run tests: \`./venv/bin/python -m pytest -q\`

For more information, see the documentation in the \`docs/\` directory.
Packaging note: ${PACKAGING_NOTE}
EOF

    success "Integration report generated: ${REPORT_FILE}"
}

main() {
    log "Starting WiFi-DensePose integration validation..."

    trap cleanup EXIT

    check_prerequisites
    validate_package_structure
    validate_imports
    validate_configuration
    validate_database
    validate_route_surface
    validate_api_endpoints
    validate_cli
    validate_background_tasks
    run_canonical_test_surface
    validate_package_build
    generate_report

    success "🎉 All integration validations passed!"
    log "Integration validation completed successfully"
}

main "$@"
