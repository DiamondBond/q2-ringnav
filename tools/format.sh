#!/bin/sh
# Format patch/ringnav.c. patch/trampoline.S, patch/link.ld, patch/contexts.inc and the
# Markdown docs have no configured formatter and are deliberately absent.
set -eu
cd "$(dirname "$0")/.."

command -v clang-format >/dev/null 2>&1 || { echo "format.sh: clang-format is not installed" >&2; exit 1; }

clang-format -i patch/ringnav.c
