#!/bin/sh
# merge.sh — single entry point for site management
#
# Handles: adding new files, removing files, and full republish.
# Automatically sorts files by type, encrypts, rebuilds indexes and manifests.
#
# Run as root from /var/www/utils/<domain>/
#
# Usage:
#   sh merge.sh                  Process add/ queue, then republish
#   sh merge.sh --publish        Full republish only (no merge step)
#   sh merge.sh --remove <file>  Remove a file from source and published site
#   sh merge.sh --rename <old> <new>  Rename a file everywhere
#
# Workflow:
#   1. Drop files into add/ directory (any type)
#   2. Run: sh merge.sh
#   3. Files are sorted into html/, pdf/, docx/, txt/ by extension
#   4. Everything is encrypted and published
#   5. Indexes and manifests are rebuilt

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="$(basename "$SCRIPT_DIR")"
UTILS="$SCRIPT_DIR"
HTDOCS="/var/www/htdocs/$DOMAIN"
ADD_DIR="$UTILS/add"

PP="$UTILS/passphrase.txt"
if [ ! -f "$PP" ] || [ ! -s "$PP" ]; then
    echo "Error: passphrase not found: $PP" >&2
    exit 1
fi

# ── Remove mode ────────────────────────────────────────────────────────────────
if [ "$1" = "--remove" ]; then
    shift
    for name in "$@"; do
        echo "Removing: $name"
        # Remove from source dirs
        for d in "$UTILS"/*/; do
            if [ -f "$d$name" ]; then
                rm "$d$name"
                echo "  removed source: $d$name"
            fi
        done
        # Remove from htdocs
        base="${name%.*}"
        for f in $(find "$HTDOCS/files" -name "$name" -o -name "$name.enc" -o -name "$name.enc.sig" 2>/dev/null); do
            rm "$f"
            echo "  removed published: $f"
        done
    done
    echo
    echo "--- Rebuilding indexes ---"
    python3 "$UTILS/gen-site-index.py" "$DOMAIN"
    echo "=== Remove complete ==="
    exit 0
fi

# ── Rename mode ────────────────────────────────────────────────────────────────
if [ "$1" = "--rename" ]; then
    old="$2"
    new="$3"
    if [ -z "$old" ] || [ -z "$new" ]; then
        echo "Usage: sh merge.sh --rename <old_filename> <new_filename>" >&2
        exit 1
    fi
    echo "Renaming: $old -> $new"
    # Rename in source dirs
    for d in "$UTILS"/*/; do
        if [ -f "$d$old" ]; then
            mv "$d$old" "$d$new"
            echo "  source: $d$old -> $d$new"
        fi
    done
    # Remove old encrypted version (will be re-created on publish)
    for f in $(find "$HTDOCS/files" -name "$old" -o -name "$old.enc" -o -name "$old.enc.sig" 2>/dev/null); do
        rm "$f"
        echo "  removed old: $f"
    done
    echo
    echo "--- Re-encrypting and rebuilding ---"
    python3 "$UTILS/encrypt-html.py" "$DOMAIN"
    echo
    python3 "$UTILS/gen-site-index.py" "$DOMAIN"
    echo "=== Rename complete ==="
    exit 0
fi

# ── Publish-only mode ─────────────────────────────────────────────────────────
if [ "$1" = "--publish" ]; then
    echo "=== $DOMAIN — full publish ==="
    echo
    echo "--- Encrypting files ---"
    python3 "$UTILS/encrypt-html.py" "$DOMAIN"
    echo
    echo "--- Building indexes and manifests ---"
    python3 "$UTILS/gen-site-index.py" "$DOMAIN"
    echo
    # Copy decrypt tools
    for f in decrypt.py DECRYPT-README.txt; do
        [ -f "$UTILS/$f" ] && cp "$UTILS/$f" "$HTDOCS/files/$f"
    done
    echo "=== Publish complete ==="
    exit 0
fi

# ── Default: merge add/ then publish ──────────────────────────────────────────
echo "=== $DOMAIN — merge + publish ==="
echo

# Process add/ queue
mkdir -p "$ADD_DIR"
count=$(find "$ADD_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l)

if [ "$count" -gt 0 ]; then
    echo "--- Sorting $count new files ---"
    for f in "$ADD_DIR"/*; do
        [ -f "$f" ] || continue
        name="$(basename "$f")"
        ext="$(echo "${name##*.}" | tr 'A-Z' 'a-z')"

        case "$ext" in
            html|htm)  dest="html" ;;
            pdf)       dest="pdf" ;;
            doc|docx)  dest="docx" ;;
            txt)       dest="txt" ;;
            *)         dest="misc" ;;
        esac

        mkdir -p "$UTILS/$dest"
        mv "$f" "$UTILS/$dest/$name"
        echo "  $name -> $dest/"
    done
    echo
else
    echo "--- No new files in add/ ---"
    echo
fi

# Full publish
echo "--- Encrypting files ---"
python3 "$UTILS/encrypt-html.py" "$DOMAIN"
echo

echo "--- Building indexes and manifests ---"
python3 "$UTILS/gen-site-index.py" "$DOMAIN"
echo

# Copy decrypt tools
for f in decrypt.py DECRYPT-README.txt; do
    [ -f "$UTILS/$f" ] && cp "$UTILS/$f" "$HTDOCS/files/$f"
done

echo "=== Merge + publish complete ==="
echo "  Site: https://$DOMAIN/"
echo "  Manifest: https://$DOMAIN/manifest.txt"
echo "  Files: $count new, $(find "$HTDOCS/files" -type f | wc -l) total"
