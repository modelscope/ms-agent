#!/bin/bash

# MS-Agent Web UI Startup Script
# This script starts both the backend server and frontend development server

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                   MS-Agent Web UI                          ║"
echo "║               Intelligent Agent Platform                   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check for Python 3.10+
PYTHON_CMD=""
for py in python3.12 python3.11 python3.10; do
    if command -v $py &> /dev/null; then
        PYTHON_CMD=$py
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}Error: Python 3.10 or higher is required but not found.${NC}"
    echo -e "${YELLOW}Please install Python 3.10+ and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}Using Python: $PYTHON_CMD ($(${PYTHON_CMD} --version))${NC}"

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: Node.js is required but not installed.${NC}"
    exit 1
fi

# Create virtual environment if not exists
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating Python virtual environment with ${PYTHON_CMD}...${NC}"
    $PYTHON_CMD -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Install Python dependencies
echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# Install ms-agent in development mode if not installed
if ! python -c "import ms_agent" 2>/dev/null; then
    echo -e "${YELLOW}Installing ms-agent...${NC}"
    pip install -q -e "$SCRIPT_DIR/../ms-agent"
fi


# Install frontend dependencies if needed
if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    cd "$SCRIPT_DIR/frontend"
    npm install
    cd "$SCRIPT_DIR"
fi

# Parse command line arguments
MODE="dev"
PORT=7860
HOST="0.0.0.0"

while [[ $# -gt 0 ]]; do
    case $1 in
        --production|-p)
            MODE="production"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build frontend for production
if [ "$MODE" = "production" ]; then
    echo -e "${YELLOW}Building frontend for production...${NC}"
    cd "$SCRIPT_DIR/frontend"
    npm run build
    cd "$SCRIPT_DIR"
fi

# Function to cleanup background processes
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend server
echo -e "${GREEN}Starting backend server on port $PORT...${NC}"
cd "$SCRIPT_DIR/backend"
if [ "$MODE" = "production" ]; then
    python main.py --host "$HOST" --port "$PORT" &
else
    python main.py --host "$HOST" --port "$PORT" --reload &
fi
BACKEND_PID=$!
cd "$SCRIPT_DIR"

# Wait for backend to start
sleep 2

if [ "$MODE" = "dev" ]; then
    # Start frontend development server
    echo -e "${GREEN}Starting frontend development server...${NC}"
    cd "$SCRIPT_DIR/frontend"
    npm run dev &
    FRONTEND_PID=$!
    cd "$SCRIPT_DIR"
    
    echo -e "\n${GREEN}✓ Development servers are running!${NC}"
    echo -e "  Backend:  ${BLUE}http://localhost:$PORT${NC}"
    echo -e "  Frontend: ${BLUE}http://localhost:5173${NC}"
    echo -e "  API Docs: ${BLUE}http://localhost:$PORT/docs${NC}"
else
    echo -e "\n${GREEN}✓ Production server is running!${NC}"
    echo -e "  Server: ${BLUE}http://$HOST:$PORT${NC}"
fi

echo -e "\n${YELLOW}Press Ctrl+C to stop the servers${NC}\n"

# Wait for processes
wait
