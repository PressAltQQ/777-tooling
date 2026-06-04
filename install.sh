#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# 777 KB enforcement tooling installer
# Usage: ./install.sh <path-to-vault> [--force]
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $0 <path-to-vault> [--force]"
    echo ""
    echo "  <path-to-vault>   Absolute or relative path to your local Obsidian vault."
    echo "  --force           Skip the Obsidian vault check (.obsidian dir not found)."
    exit 1
}

# Parse arguments
VAULT=""
FORCE=false

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        -*) echo "Unknown option: $arg"; usage ;;
        *)
            if [ -z "$VAULT" ]; then
                VAULT="$arg"
            else
                echo "Unexpected argument: $arg"
                usage
            fi
            ;;
    esac
done

if [ -z "$VAULT" ]; then
    usage
fi

# Expand tilde
VAULT="${VAULT/#\~/$HOME}"

echo "==> 777 KB enforcement tooling installer"
echo "    Vault: $VAULT"
echo ""

# Check vault path exists
if [ ! -d "$VAULT" ]; then
    echo "ERROR: Vault path does not exist: $VAULT"
    exit 1
fi

# Check it looks like an Obsidian vault
if [ ! -d "$VAULT/.obsidian" ]; then
    if [ "$FORCE" = true ]; then
        echo "WARNING: No .obsidian directory found in '$VAULT'. Proceeding anyway (--force)."
    else
        echo "ERROR: '$VAULT' does not look like an Obsidian vault (.obsidian directory not found)."
        echo "       If you are sure this is the right path, re-run with --force."
        exit 1
    fi
fi

# Check python3 is available
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. The validator requires Python 3."
    echo "       Install Python 3 (https://www.python.org/downloads/) and re-run."
    exit 1
fi

echo "--> python3 found: $(command -v python3)"
echo ""

# Create target directories
echo "--> Creating target directories..."
mkdir -p "$VAULT/.claude"
mkdir -p "$VAULT/_meta"

# Copy files
echo "--> Installing .claude/settings.json..."
cp "$SCRIPT_DIR/.claude/settings.json" "$VAULT/.claude/settings.json"

echo "--> Installing _meta/validate.py..."
cp "$SCRIPT_DIR/_meta/validate.py" "$VAULT/_meta/validate.py"

echo "--> Installing _meta/schema.json..."
cp "$SCRIPT_DIR/_meta/schema.json" "$VAULT/_meta/schema.json"

echo ""
echo "==> Installation complete. Files installed:"
echo "    $VAULT/.claude/settings.json"
echo "    $VAULT/_meta/validate.py"
echo "    $VAULT/_meta/schema.json"
echo ""
echo "==> REMINDERS:"
echo ""
echo "    1. Dataview plugin (REQUIRED for dashboards):"
echo "       In Obsidian → Settings → Community plugins → Browse → search 'Dataview' → Install & Enable."
echo "       This plugin is NOT bundled — install it once per machine."
echo ""
echo "    2. Optional — see .py/.json files inside Obsidian:"
echo "       Settings → Files & Links → enable 'Detect all file extensions'."
echo ""
echo "    NOTE: The validation hard gate is now ACTIVE on this machine."
echo "          Claude Code will validate frontmatter before any write to enforced zones."
