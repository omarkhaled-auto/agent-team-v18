#!/bin/bash
# Run this AFTER closing the Claude Code session to avoid rate limits.
# Usage: bash scripts/run_mini_build.sh

set -e

BUILD_DIR="/c/Users/Omar Khaled/AppData/Local/Temp/mini-test-build"

echo "=== Cleaning previous run ==="
rm -rf "$BUILD_DIR/.agent-team"

echo "=== Starting mini build ==="
echo "This will show all upgraded validators firing on real generated code."
echo ""

cd "$BUILD_DIR"
agent-team-v15 --depth quick --config agent-team.yml \
  "Build the Mini Task Tracker per prd.md. This is a QUICK build — minimal agents, fast execution." \
  2>&1 | tee /tmp/mini_build_full_output.txt

echo ""
echo "=== Build complete ==="
echo "Full output: /tmp/mini_build_full_output.txt"
echo ""
echo "=== Checking what our validators found ==="
grep -i "SCHEMA\|ENUM\|SOFTDEL\|SHAPE\|AUTH\|INFRA\|ROUTE\|quality\|schema_validation\|integration.*gate\|blocking\|convergence\|regression" /tmp/mini_build_full_output.txt || echo "No validator output found"
