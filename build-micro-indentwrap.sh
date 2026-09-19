#!/usr/bin/env bash
set -euo pipefail

MICRO_VERSION="${MICRO_VERSION:-v2.0.15}"
REPO_URL="${REPO_URL:-https://github.com/zyedidia/micro.git}"
PATCH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/patches"
CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/micro-indentwrap"
SRC_DIR="$CACHE_ROOT/micro-$MICRO_VERSION"
OUT_BIN="${OUT_BIN:-$HOME/.local/bin/micro-indentwrap}"
RUN_TESTS="${RUN_TESTS:-1}"

case "$SRC_DIR" in
    "$CACHE_ROOT"/micro-*) ;;
    *)
        printf 'Refusing to remove unexpected source directory: %s\n' "$SRC_DIR" >&2
        exit 1
        ;;
esac

command -v git >/dev/null || { printf 'git is required\n' >&2; exit 1; }
command -v go >/dev/null || { printf 'go is required\n' >&2; exit 1; }
command -v make >/dev/null || { printf 'make is required\n' >&2; exit 1; }

mkdir -p "$CACHE_ROOT" "$(dirname -- "$OUT_BIN")"
rm -rf "$SRC_DIR"

git clone --depth 1 --branch "$MICRO_VERSION" "$REPO_URL" "$SRC_DIR"
shopt -s nullglob
patch_files=("$PATCH_DIR"/*.patch)
shopt -u nullglob
if (( ${#patch_files[@]} == 0 )); then
	printf 'No patches found in %s\n' "$PATCH_DIR" >&2
	exit 1
fi
for patch_file in "${patch_files[@]}"; do
	printf 'Applying %s\n' "$(basename "$patch_file")"
	git -C "$SRC_DIR" apply "$patch_file"
done

if [ "$RUN_TESTS" != "0" ]; then
    (
        cd "$SRC_DIR"
        go test ./internal/display ./internal/config ./internal/buffer ./internal/action
    )
fi

make -C "$SRC_DIR" build
install -m 0755 "$SRC_DIR/micro" "$OUT_BIN"

printf 'Built %s\n' "$OUT_BIN"
"$OUT_BIN" -version
