#!/bin/sh
# Format the file types this repo has style tools for: C (clang-format) and Markdown/JSON
# (prettier). With --check, report differences instead of writing.
# patch/trampoline.S, patch/link.ld and patch/contexts.inc have no usable formatter and are
# deliberately absent.
set -eu
cd "$(dirname "$0")/.."

for tool in clang-format prettier; do
    command -v "$tool" >/dev/null 2>&1 || { echo "format.sh: $tool is not installed" >&2; exit 1; }
done

if [ "${1:-}" = --check ]; then
    clang-format --dry-run --Werror patch/ringnav.c
    prettier --check README.md dist/manifest.json
else
    clang-format -i patch/ringnav.c
    prettier --write README.md dist/manifest.json
fi
