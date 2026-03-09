#!/bin/sh
# setup.sh — one-time setup for an unveil encrypted website
#
# Usage: sh setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$SCRIPT_DIR/site.conf"
[ -f "$CONF" ] || { echo "Error: site.conf not found" >&2; exit 1; }
eval "$(grep -v '^#' "$CONF" | grep '=' | sed 's/\$DOMAIN/'$(grep '^DOMAIN=' "$CONF" | cut -d= -f2)'/g')"

echo "=== unveil setup: $DOMAIN ==="
echo

# Directories
echo "--- Directories ---"
mkdir -p "$UTILS_DIR"/{html,pdf,docx,txt,add,keys,misc}
mkdir -p "$HTDOCS_DIR"/files/{html,pdf,docx,txt,misc}
echo "  $UTILS_DIR/"
echo "  $HTDOCS_DIR/"
echo

# GPG key
echo "--- GPG key ---"
if gpg --list-secret-keys 2>/dev/null | grep -q sec; then
    echo "  Already imported"
else
    keyfile=""
    for f in "$UTILS_DIR/keys/gpg-private.asc" "$UTILS_DIR/gpg-private.asc"; do
        [ -f "$f" ] && keyfile="$f" && break
    done
    if [ -n "$keyfile" ]; then
        gpg --batch --import "$keyfile"
        echo "  Imported from: $keyfile"
    else
        echo "  Generating new keypair..."
        gpg --batch --gen-key <<EOF
Key-Type: RSA
Key-Length: 4096
Name-Real: $DOMAIN
Name-Email: $GPG_EMAIL
Expire-Date: 0
%no-protection
%commit
EOF
        gpg --armor --export-secret-keys "$GPG_EMAIL" > "$UTILS_DIR/keys/gpg-private.asc"
        echo "  Saved to keys/gpg-private.asc — BACK THIS UP"
    fi
fi
gpg --armor --export > "$HTDOCS_DIR/files/pubkey.asc" 2>/dev/null
echo "  Public key -> $HTDOCS_DIR/files/pubkey.asc"
echo

# Passphrase
echo "--- Passphrase ---"
PP="$UTILS_DIR/passphrase.txt"
if [ -f "$PP" ] && [ -s "$PP" ]; then
    echo "  Already exists"
else
    sh "$SCRIPT_DIR/gen-passphrase.sh" ${PASSPHRASE_WORDS:-12} > "$PP"
    chmod 600 "$PP"
    echo "  WRITE THIS DOWN — LOSS = PERMANENT DATA LOSS"
    echo
    cat "$PP"
    echo
fi
echo

echo "=== Setup complete ==="
echo "Next: copy files into $UTILS_DIR/{html,pdf,...}/ then run: sh merge.sh"
