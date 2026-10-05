#!/usr/bin/env bash
# Build dist/when-free.mcpb, the Claude Desktop extension: this folder plus a copy of src/whenfree.
# Needs Node (for npx). Run from anywhere.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/src/whenfree/__init__.py")"
for f in manifest.json pyproject.toml; do
  grep -q "\"$version\"" "$here/$f" || { echo "error: $f does not say version $version" >&2; exit 1; }
done

cp "$here/manifest.json" "$here/pyproject.toml" "$here/server.py" "$work/"
mkdir -p "$work/src"
cp -R "$root/src/whenfree" "$work/src/"
find "$work" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$root/LICENSE" "$work/"

npx -y @anthropic-ai/mcpb validate "$work/manifest.json"
mkdir -p "$root/dist"
npx -y @anthropic-ai/mcpb pack "$work" "$root/dist/when-free.mcpb"
echo "built $root/dist/when-free.mcpb"
