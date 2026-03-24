#!/bin/bash

# Agentic Insight v2 Benchmark Runner
# This script helps reproduce the official benchmark results.
# Must be run from the repository root directory.
#
# Usage:
#   Single demo query:   bash projects/deep_research/v2/run_benchmark.sh
#   Full benchmark:      DR_BENCH_ROOT=/path/to/bench bash projects/deep_research/v2/run_benchmark.sh

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================="
echo "Agentic Insight v2 Benchmark Runner"
echo "========================================="
echo ""

# Locate Python executable early for both modes
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo -e "${RED}Error: Neither 'python' nor 'python3' is available in PATH.${NC}"
    exit 1
fi

# Use caffeinate on macOS when available; otherwise run normally.
RUN_PREFIX=()
if command -v caffeinate >/dev/null 2>&1; then
    RUN_PREFIX=("caffeinate" "-i")
else
    echo -e "${YELLOW}Warning: 'caffeinate' not found, running without sleep prevention.${NC}"
fi

# Verify we are at the repository root
if [ ! -f "ms_agent/cli/cli.py" ]; then
    echo -e "${RED}Error: This script must be run from the repository root directory.${NC}"
    echo "  cd /path/to/ms-agent"
    echo "  bash projects/deep_research/v2/run_benchmark.sh"
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found in repository root!${NC}"
    echo "Please create .env file by copying .env.example:"
    echo "  cp projects/deep_research/.env.example .env"
    echo "  # Then edit .env to add your API keys"
    exit 1
fi

# Source .env file
echo -e "${GREEN}Loading environment variables from .env...${NC}"
set -a  # Export all variables
source .env
set +a

# Validate required environment variables
if [ -z "$OPENAI_API_KEY" ] || [ -z "$OPENAI_BASE_URL" ]; then
    echo -e "${RED}Error: OPENAI_API_KEY or OPENAI_BASE_URL not set in .env${NC}"
    exit 1
fi

# Check for search engine API key
if [ -z "$EXA_API_KEY" ] && [ -z "$SERPAPI_API_KEY" ]; then
    echo -e "${YELLOW}Warning: Neither EXA_API_KEY nor SERPAPI_API_KEY is set.${NC}"
    echo -e "${YELLOW}The system will use arxiv (academic search only).${NC}"
    echo ""
fi

echo -e "${GREEN}Environment variables loaded successfully!${NC}"
echo "  OPENAI_BASE_URL: $OPENAI_BASE_URL"
echo "  EXA_API_KEY: $([ -n "$EXA_API_KEY" ] && echo "✓ Set" || echo "✗ Not set")"
echo "  SERPAPI_API_KEY: $([ -n "$SERPAPI_API_KEY" ] && echo "✓ Set" || echo "✗ Not set")"
echo ""

# Check if DR_BENCH_ROOT is set
if [ -z "$DR_BENCH_ROOT" ]; then
    echo -e "${YELLOW}Warning: DR_BENCH_ROOT not set.${NC}"
    echo -e "${YELLOW}Using default benchmark query...${NC}"
    echo ""

    # Run a simple benchmark query
    QUERY="Provide a comprehensive survey of recent advances in large language models (LLMs), covering key developments in the last 12 months including architecture innovations, training techniques, and real-world applications."
    OUTPUT_DIR="output/deep_research/benchmark_run"

    echo -e "${GREEN}Running benchmark with query:${NC}"
    echo "  \"$QUERY\""
    echo ""
    echo -e "${GREEN}Output directory: $OUTPUT_DIR${NC}"
    echo ""

    # Run the benchmark
    PYTHONPATH=. "$PYTHON_BIN" ms_agent/cli/cli.py run \
        --config projects/deep_research/v2/researcher.yaml \
        --query "$QUERY" \
        --trust_remote_code true \
        --output_dir "$OUTPUT_DIR"

    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}Benchmark completed!${NC}"
    echo -e "${GREEN}Results saved to: $OUTPUT_DIR${NC}"
    echo -e "${GREEN}Final report: $OUTPUT_DIR/final_report.md${NC}"
    echo -e "${GREEN}=========================================${NC}"

else
    echo -e "${GREEN}DR_BENCH_ROOT detected: $DR_BENCH_ROOT${NC}"
    echo -e "${YELLOW}Running full benchmark suite...${NC}"
    echo ""

    # Benchmark subprocess tuning (override via env vars if needed)
    export DR_BENCH_POST_FINISH_GRACE_S="${DR_BENCH_POST_FINISH_GRACE_S:-180}"
    export DR_BENCH_POST_REPORT_EXIT_GRACE_S="${DR_BENCH_POST_REPORT_EXIT_GRACE_S:-3600}"
    export DR_BENCH_REPORT_STABLE_WINDOW_S="${DR_BENCH_REPORT_STABLE_WINDOW_S:-10}"
    export DR_BENCH_SUBPROCESS_POLL_INTERVAL_S="${DR_BENCH_SUBPROCESS_POLL_INTERVAL_S:-0.5}"
    export DR_BENCH_SUBPROCESS_TERMINATE_TIMEOUT_S="${DR_BENCH_SUBPROCESS_TERMINATE_TIMEOUT_S:-30}"
    export DR_BENCH_SUBPROCESS_KILL_TIMEOUT_S="${DR_BENCH_SUBPROCESS_KILL_TIMEOUT_S:-30}"

    # Check if DR_BENCH_ROOT exists
    if [ ! -d "$DR_BENCH_ROOT" ]; then
        echo -e "${RED}Error: DR_BENCH_ROOT directory not found: $DR_BENCH_ROOT${NC}"
        exit 1
    fi

    # Check if query file exists
    QUERY_FILE="$DR_BENCH_ROOT/data/prompt_data/query.jsonl"
    if [ ! -f "$QUERY_FILE" ]; then
        echo -e "${RED}Error: Query file not found: $QUERY_FILE${NC}"
        exit 1
    fi

    # Set default values
    MODEL_NAME="${MODEL_NAME:-ms_deepresearch_v2_benchmark}"
    OUTPUT_JSONL="${OUTPUT_JSONL:-$DR_BENCH_ROOT/data/test_data/raw_data/${MODEL_NAME}.jsonl}"
    WORK_ROOT="${WORK_ROOT:-temp/benchmark_runs}"
    WORKERS="${WORKERS:-2}"
    LIMIT="${LIMIT:-0}"

    # Validate numeric inputs early for clearer errors
    if ! [[ "$WORKERS" =~ ^[0-9]+$ ]] || [ "$WORKERS" -lt 1 ]; then
        echo -e "${RED}Error: WORKERS must be a positive integer. Got: $WORKERS${NC}"
        exit 1
    fi
    if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}Error: LIMIT must be a non-negative integer. Got: $LIMIT${NC}"
        exit 1
    fi

    echo "Configuration:"
    echo "  Query file: $QUERY_FILE"
    echo "  Output JSONL: $OUTPUT_JSONL"
    echo "  Model name: $MODEL_NAME"
    echo "  Work root: $WORK_ROOT"
    echo "  Workers: $WORKERS"
    echo "  Limit: $LIMIT (0 = no limit)"
    echo ""

    # Run the full benchmark
    PYTHONPATH=. "${RUN_PREFIX[@]}" "$PYTHON_BIN" projects/deep_research/v2/eval/dr_bench_runner.py \
        --query_file "$QUERY_FILE" \
        --output_jsonl "$OUTPUT_JSONL" \
        --model_name "$MODEL_NAME" \
        --work_root "$WORK_ROOT" \
        --limit "$LIMIT" \
        --workers "$WORKERS" \
        --trust_remote_code

    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}Full benchmark suite completed!${NC}"
    echo -e "${GREEN}Results saved to: $OUTPUT_JSONL${NC}"
    echo -e "${GREEN}=========================================${NC}"
fi
