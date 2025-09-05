#!/bin/bash

# Low Priority Reddit Scraper Runner
# This script runs the subreddit scraper with lower network and CPU priority
# to avoid competing with user's important network traffic

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/subreddit_frontpage_scraper.py"

# Default settings
NICE_LEVEL=10
BANDWIDTH_LIMIT=""
USE_TRICKLE=false

# Help function
show_help() {
    cat << EOF
Usage: $0 [OPTIONS] -- [SCRAPER_ARGS]

Run the Reddit scraper with low network and CPU priority.

OPTIONS:
    -n, --nice LEVEL        Set nice level (0-19, higher = lower priority, default: 10)
    -b, --bandwidth LIMIT   Bandwidth limit (e.g., 500k, 1m) using trickle if available
    -t, --use-trickle       Force use of trickle for bandwidth limiting
    -h, --help             Show this help

EXAMPLES:
    # Basic low priority run
    $0 -- --subs r/technology r/programming

    # With bandwidth limiting (500 KB/s)
    $0 -b 500k -- --subs r/technology --min-posts 30

    # Custom nice level and bandwidth
    $0 -n 15 -b 1m -- --subs r/technology --disable-images

    # All arguments after -- are passed to the scraper
    $0 -- --subs r/tech --headless --min-posts 50 --disable-images

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--nice)
            NICE_LEVEL="$2"
            shift 2
            ;;
        -b|--bandwidth)
            BANDWIDTH_LIMIT="$2"
            USE_TRICKLE=true
            shift 2
            ;;
        -t|--use-trickle)
            USE_TRICKLE=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate nice level
if [[ ! "$NICE_LEVEL" =~ ^[0-9]+$ ]] || [ "$NICE_LEVEL" -lt 0 ] || [ "$NICE_LEVEL" -gt 19 ]; then
    echo "Error: Nice level must be between 0-19"
    exit 1
fi

# Check if python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "Error: Python script not found at $PYTHON_SCRIPT"
    exit 1
fi

# Determine Python command
PYTHON_CMD="python3"
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
fi

# Build command
CMD_PARTS=()

# Add nice for CPU priority
CMD_PARTS+=("nice" "-n" "$NICE_LEVEL")

# Add trickle for bandwidth limiting if requested and available
if [ "$USE_TRICKLE" = true ]; then
    if command -v trickle >/dev/null 2>&1; then
        if [ -n "$BANDWIDTH_LIMIT" ]; then
            # Convert bandwidth limit to trickle format (KB/s)
            TRICKLE_LIMIT=$(echo "$BANDWIDTH_LIMIT" | sed 's/k$//' | sed 's/m$/000/' | sed 's/M$/000/')
            CMD_PARTS+=("trickle" "-d" "$TRICKLE_LIMIT" "-u" "$TRICKLE_LIMIT")
            echo "[priority] Using trickle to limit bandwidth to $BANDWIDTH_LIMIT"
        else
            CMD_PARTS+=("trickle" "-d" "500" "-u" "200")  # Default limits
            echo "[priority] Using trickle with default bandwidth limits (500KB/s down, 200KB/s up)"
        fi
    else
        echo "[priority] Warning: trickle not available, skipping bandwidth limiting"
        echo "[priority] Install with: brew install trickle (macOS) or apt-get install trickle (Linux)"
    fi
fi

# Add the Python command and script
CMD_PARTS+=("$PYTHON_CMD" "$PYTHON_SCRIPT" "--low-priority" "--nice-level" "$NICE_LEVEL")

# Add user arguments
CMD_PARTS+=("$@")

# Print the command being run
echo "[priority] Running with low priority (nice: $NICE_LEVEL)"
echo "[priority] Command: ${CMD_PARTS[*]}"
echo ""

# Execute the command
exec "${CMD_PARTS[@]}"
