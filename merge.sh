#!/bin/sh
# merge.sh — single entry point for unveil site management
#
# Usage:
#   sh merge.sh                  Process add/ queue, then publish
#   sh merge.sh --publish        Full republish only
#   sh merge.sh --remove <file>  Remove a file from site
#   sh merge.sh --rename <o> <n> Rename a file everywhere

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load site.conf
CONF="$SCRIPT_DIR/site.conf"
[ -f "$CONF" ] || { echo "Error: site.conf not found in $SCRIPT_DIR" >&2; exit 1; }
eval "$(grep -v '^#' "$CONF" | grep '=' | sed 's/\$DOMAIN/'$(grep '^DOMAIN=' "$CONF" | cut -d= -f2)'/g')"

UTILS="$UTILS_DIR"
HTDOCS="$HTDOCS_DIR"
ADD="$UTILS/add"

[ -f "$UTILS/passphrase.txt" ] && [ -s "$UTILS/passphrase.txt" ] || {
    echo "Error: passphrase not found" >&2; exit 1
}

do_publish() {
    python3 "$SCRIPT_DIR/locksite.py" publish
    for f in decrypt.py DECRYPT-README.txt; do
        [ -f "$UTILS/$f" ] && cp "$UTILS/$f" "$HTDOCS/files/$f"
    done
}

# ── Remove ─────────────────────────────────────────────────────────────────
if [ "$1" = "--remove" ]; then
    shift
    for name in "$@"; do
        echo "Removing: $name"
        for d in "$UTILS"/*/; do
            [ -f "$d$name" ] && rm "$d$name" && echo "  source: $d$name"
        done
        find "$HTDOCS/files" \( -name "$name" -o -name "$name.enc" -o -name "$name.enc.sig" \) \
            -exec rm {} \; -exec echo "  published: {}" \; 2>/dev/null
    done
    echo; python3 "$SCRIPT_DIR/locksite.py" index
    exit 0
fi

# ── Rename ─────────────────────────────────────────────────────────────────
if [ "$1" = "--rename" ]; then
    [ -z "$2" ] || [ -z "$3" ] && { echo "Usage: merge.sh --rename <old> <new>" >&2; exit 1; }
    echo "Renaming: $2 -> $3"
    for d in "$UTILS"/*/; do
        [ -f "$d$2" ] && mv "$d$2" "$d$3" && echo "  source: $d$2 -> $d$3"
    done
    find "$HTDOCS/files" \( -name "$2" -o -name "$2.enc" -o -name "$2.enc.sig" \) \
        -exec rm {} \; 2>/dev/null
    do_publish
    exit 0
fi

# ── Publish only ───────────────────────────────────────────────────────────
if [ "$1" = "--publish" ]; then
    do_publish
    exit 0
fi

# ── Default: merge add/ then publish ──────────────────────────────────────
mkdir -p "$ADD"
count=$(find "$ADD" -maxdepth 1 -type f 2>/dev/null | wc -l)

if [ "$count" -gt 0 ]; then
    echo "--- Sorting $count new files ---"
    for f in "$ADD"/*; do
        [ -f "$f" ] || continue
        name="$(basename "$f")"
        ext="$(echo "${name##*.}" | tr 'A-Z' 'a-z')"
        case "$ext" in
            html|htm) dest="html" ;; pdf) dest="pdf" ;;
            doc|docx) dest="docx" ;; txt) dest="txt" ;; *) dest="misc" ;;
        esac
        mkdir -p "$UTILS/$dest"
        mv "$f" "$UTILS/$dest/$name"
        echo "  $name -> $dest/"
    done
    echo
else
    echo "--- No new files in add/ ---"
fi

do_publish
echo "  Site: https://$DOMAIN/"
echo "  Manifest: https://$DOMAIN/manifest.txt"
