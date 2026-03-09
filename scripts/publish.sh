#!/bin/sh
# publish.sh — encrypt all files and publish to web root
#
# Run from: /var/www/utils/<domain>/
# Reads source files from subdirs (html/, pdf/, docx/, txt/, etc.)
# Encrypts everything → /var/www/htdocs/<domain>/files/
# Builds encrypted index.html → /var/www/htdocs/<domain>/index.html
#
# Usage: sh publish.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="$(basename "$SCRIPT_DIR")"

echo "=== $DOMAIN — publish ==="
echo

# Step 1: Encrypt all files
echo "--- Encrypting files ---"
python3 "$SCRIPT_DIR/encrypt-html.py" "$DOMAIN"
echo

# Step 2: Generate encrypted index.html
echo "--- Building index ---"
python3 "$SCRIPT_DIR/gen-site-index.py" "$DOMAIN"
echo

# Step 3: Copy decrypt tools to files/ for offline use
HTDOCS="/var/www/htdocs/$DOMAIN"
for f in decrypt.py DECRYPT-README.txt; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$HTDOCS/files/$f"
    fi
done

echo "=== Publish complete ==="
echo "  Site: $HTDOCS/"
echo "  Index: $HTDOCS/index.html"
echo "  Files: $HTDOCS/files/"
