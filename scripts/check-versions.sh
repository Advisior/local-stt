#!/bin/bash
# Fail if the version is not identical across all sources that declare one.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

pyproject=$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -1)
package=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' "$PROJECT_DIR/src/claude_stt/__init__.py" | head -1)
plugin=$(python3 -c "import json;print(json.load(open('$PROJECT_DIR/.claude-plugin/plugin.json'))['version'])")
marketplace=$(python3 -c "import json;print(json.load(open('$PROJECT_DIR/.claude-plugin/marketplace.json'))['plugins'][0]['version'])")

echo "pyproject.toml            $pyproject"
echo "claude_stt/__init__.py    $package"
echo "plugin.json               $plugin"
echo "marketplace.json          $marketplace"

status=0
for v in "$package" "$plugin" "$marketplace"; do
    [[ "$v" == "$pyproject" ]] || status=1
done

if [[ $status -ne 0 ]]; then
    echo "ERROR: versions disagree, pyproject.toml is the source of truth" >&2
    exit 1
fi

echo "OK: all sources agree on $pyproject"
