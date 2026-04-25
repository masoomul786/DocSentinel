#!/usr/bin/env bash
# DocSentinel — fixed start.sh
# Bugs fixed:
#   - set -e removed (caused silent exits on non-fatal errors)
#   - Docker: rm -f old container before run (was silently failing on re-runs)
#   - Docker: pull image before run to avoid "image not found" failures
#   - Docker: daemon liveness check added
#   - Backend: actual health-poll loop (was fixed 2s sleep)
#   - Backend: port-in-use check before starting uvicorn
#   - pip install: errors no longer kill script

set -uo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

clear

echo -e "${CYAN}"
cat << 'EOF'
 ██████╗  ██████╗  ██████╗███████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗
 ██╔══██╗██╔═══██╗██╔════╝██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║
 ██║  ██║██║   ██║██║     ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║
 ██║  ██║██║   ██║██║     ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║
 ██████╔╝╚██████╔╝╚██████╗███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗
 ╚═════╝  ╚═════╝  ╚═════╝╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
EOF
echo -e "${NC}"
echo -e "${DIM}                 Self-Healing Multimodal Document Intelligence${NC}"
echo -e "${DIM}                 100% Offline | ARM Ready | Powered by Actian VectorAI DB${NC}"
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIDS=()
ACTIAN_RUNNING=false

cleanup() {
    echo ""
    echo -e "${YELLOW} Shutting down DocSentinel...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    # Stop Docker container gracefully
    docker stop actian-vectorai 2>/dev/null || true
    echo -e "${GREEN} DocSentinel stopped. Goodbye.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

wait_for_qdrant() {
    local i=0
    while [ $i -lt 20 ]; do
        if curl -s --max-time 1 http://localhost:6333/healthz &>/dev/null; then
            echo -e "      ${GREEN}Actian VectorAI DB is ready (port 6333)${NC}"
            return 0
        fi
        sleep 1
        i=$((i+1))
    done
    echo -e "      ${YELLOW}[WARN] Actian VectorAI DB did not respond — mock mode active${NC}"
    return 1
}

wait_for_backend() {
    local i=0
    echo -ne "      Waiting"
    while [ $i -lt 40 ]; do
        if curl -s --max-time 1 http://localhost:8000/api/health &>/dev/null; then
            echo -e " ${GREEN}ready!${NC}"
            echo -e "      ${GREEN}Backend running on http://localhost:8000${NC}"
            return 0
        fi
        # Detect uvicorn crash early
        if ! kill -0 $BACKEND_PID 2>/dev/null; then
            echo -e " ${RED}CRASHED${NC}"
            echo -e "      ${RED}[ERROR] Backend crashed on startup. Last log:${NC}"
            tail -20 "$SCRIPT_DIR/backend.log" 2>/dev/null | sed "s/^/      /"
            echo -e "      ${DIM}Fix: cd backend && source .venv/bin/activate && python -m uvicorn main:app${NC}"
            return 1
        fi
        echo -ne "."
        sleep 1
        i=$((i+1))
    done
    echo ""
    echo -e "      ${YELLOW}[WARN] Backend slow to start — opening UI anyway${NC}"
    return 0
}

# ── [1/5] Python ──────────────────────────────────────────────────────────────
echo -e "${BOLD}[1/5]${NC} Checking Python..."
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON="$cmd"; break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}[ERROR] Python 3.9+ not found. Install from https://python.org${NC}"
    exit 1
fi
echo -e "      ${GREEN}Found:${NC} $($PYTHON --version)"
echo ""

# ── [2/5] Actian VectorAI DB ──────────────────────────────────────────────────
echo -e "${BOLD}[2/5]${NC} Checking Actian VectorAI DB..."

if curl -s --max-time 2 http://localhost:6333/healthz &>/dev/null; then
    echo -e "      ${GREEN}Already running on port 6333${NC}"
    ACTIAN_RUNNING=true

elif command -v qdrant &>/dev/null; then
    echo -e "      Starting native qdrant..."
    mkdir -p "$SCRIPT_DIR/actian_data"
    qdrant --storage-path "$SCRIPT_DIR/actian_data" &
    PIDS+=($!)
    wait_for_qdrant && ACTIAN_RUNNING=true

elif command -v docker &>/dev/null; then
    # Check daemon is alive
    if ! docker info &>/dev/null; then
        echo -e "      ${YELLOW}[WARN] Docker installed but not running. Start Docker Desktop first.${NC}"
        echo -e "      ${DIM}Running in mock mode for now...${NC}"
    else
        echo -e "      Starting via Docker..."
        mkdir -p "$SCRIPT_DIR/actian_data"

        # Remove any previous stopped container (this was the root cause of silent failures)
        docker rm -f actian-vectorai 2>/dev/null || true

        # Pull image silently so first-run always works
        echo -e "      Pulling qdrant/qdrant image (cached if already downloaded)..."
        docker pull qdrant/qdrant:latest 2>/dev/null || true

        docker run -d \
            --name actian-vectorai \
            --restart unless-stopped \
            -p 6333:6333 \
            -p 6334:6334 \
            -v "$SCRIPT_DIR/actian_data:/qdrant/storage:z" \
            qdrant/qdrant:latest

        if [ $? -eq 0 ]; then
            wait_for_qdrant && ACTIAN_RUNNING=true
        else
            echo -e "      ${YELLOW}[WARN] docker run failed — mock mode active${NC}"
        fi
    fi
else
    echo -e "      ${YELLOW}[WARN] Neither qdrant nor Docker found — mock mode active${NC}"
    echo -e "      ${DIM}Install Docker Desktop: https://www.docker.com/products/docker-desktop${NC}"
    echo -e "      ${DIM}Or native qdrant:       https://github.com/qdrant/qdrant/releases${NC}"
fi
echo ""

# ── [3/5] Python dependencies ─────────────────────────────────────────────────
echo -e "${BOLD}[3/5]${NC} Installing Python dependencies..."
cd "$SCRIPT_DIR/backend"

if [ ! -d ".venv" ]; then
    echo -e "      Creating virtual environment..."
    $PYTHON -m venv .venv
fi

source .venv/bin/activate

pip install --upgrade pip -q 2>/dev/null || true
pip install -r requirements.txt -q 2>/dev/null || true

# Verify critical imports actually work — pip can silently fail on torch/heavy deps
if ! $PYTHON -c "import fastapi, uvicorn, httpx, pydantic" 2>/dev/null; then
    echo -e "      ${YELLOW}[WARN] Core imports missing — force installing...${NC}"
    pip install fastapi "uvicorn[standard]" httpx pydantic python-multipart websockets aiofiles pypdf python-dotenv "qdrant-client" Pillow -q
fi

if ! $PYTHON -c "import fastapi, uvicorn, httpx, pydantic" 2>/dev/null; then
    echo -e "      ${RED}[ERROR] Cannot import core packages. Try: pip install fastapi uvicorn httpx pydantic${NC}"
    exit 1
fi
echo -e "      ${GREEN}Dependencies ready${NC}"
cd "$SCRIPT_DIR"
echo ""

# ── [4/5] LM Studio ───────────────────────────────────────────────────────────
echo -e "${BOLD}[4/5]${NC} Checking LM Studio..."
if curl -s --max-time 2 http://localhost:1234/v1/models &>/dev/null; then
    echo -e "      ${GREEN}LM Studio running on port 1234${NC}"
else
    echo -e "      ${YELLOW}[INFO] LM Studio not running — UI will use demo mode${NC}"
    echo -e "      ${DIM}For real AI: open LM Studio → load Qwen2.5-VL → enable server${NC}"
fi
echo ""

# ── [5/5] Backend ─────────────────────────────────────────────────────────────
echo -e "${BOLD}[5/5]${NC} Starting DocSentinel backend..."

# Free port 8000 if busy
if lsof -i :8000 -t &>/dev/null 2>&1; then
    echo -e "      Port 8000 in use — freeing it..."
    lsof -i :8000 -t | xargs kill -9 2>/dev/null || true
    sleep 1
fi

cd "$SCRIPT_DIR/backend"
source .venv/bin/activate
export DOCSENTINEL_ROOT="$SCRIPT_DIR"
$PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload > "$SCRIPT_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
PIDS+=($BACKEND_PID)
cd "$SCRIPT_DIR"

wait_for_backend
echo ""

# ── Ready ─────────────────────────────────────────────────────────────────────
echo -e "${CYAN}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e " ${GREEN}${BOLD}DOCSENTINEL IS READY${NC}"
echo ""
echo -e " ${BOLD}Frontend:${NC}    ${CYAN}http://localhost:8000${NC}"
echo -e " ${BOLD}API Docs:${NC}    ${CYAN}http://localhost:8000/docs${NC}"
[ "$ACTIAN_RUNNING" = true ] && echo -e " ${BOLD}Actian DB:${NC}   ${CYAN}http://localhost:6333/dashboard${NC}"
echo ""
echo -e " ${DIM}Stack: Actian VectorAI DB | Qwen2.5-VL via LM Studio | MinerU | Self-Healing Loop${NC}"
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""

FRONTEND_URL="http://localhost:8000"
if curl -s --max-time 2 http://localhost:8000/api/health &>/dev/null; then
    command -v xdg-open &>/dev/null && xdg-open "$FRONTEND_URL" 2>/dev/null &
    command -v open      &>/dev/null && open      "$FRONTEND_URL" 2>/dev/null &
    echo -e " ${DIM}Browser opened. Press Ctrl+C to stop all services.${NC}"
else
    echo -e " ${YELLOW}Open manually: ${CYAN}http://localhost:8000${NC}"
    echo -e " ${DIM}Debug log: tail -f backend.log${NC}"
fi
echo ""

wait
