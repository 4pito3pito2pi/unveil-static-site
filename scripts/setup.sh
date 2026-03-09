#!/bin/sh
# setup.sh — one-time setup for encrypted website publishing
#
# Run from: /var/www/utils/<domain>/
# Creates: passphrase, GPG keypair, directory structure
#
# Usage: sh setup.sh
#        sh /var/www/utils/dpcpbp.org/setup.sh

set -e

# Determine domain from our directory name
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="$(basename "$SCRIPT_DIR")"
UTILS="$SCRIPT_DIR"
HTDOCS="/var/www/htdocs/$DOMAIN"

echo "=== $DOMAIN — setup ==="
echo

# ── Directories ────────────────────────────────────────────────────────────────
echo "--- Directories ---"
mkdir -p "$UTILS/html" "$UTILS/add" "$UTILS/keys"
mkdir -p "$HTDOCS/files/html"
for d in "$UTILS"/*/; do
    dname="$(basename "$d")"
    case "$dname" in add|keys) continue ;; esac
    mkdir -p "$HTDOCS/files/$dname"
done
echo "  $UTILS"
echo "    html/       source HTML files"
echo "    add/        drop new files here for merge.sh"
echo "    keys/       GPG keys"
echo "  $HTDOCS"
echo "    index.html  encrypted home page"
echo "    files/      encrypted files (mirrors source structure)"
echo

# ── GPG key ────────────────────────────────────────────────────────────────────
echo "--- GPG key ---"
if gpg --list-secret-keys 2>/dev/null | grep -q sec; then
    echo "  GPG key already imported"
else
    # Check for existing key file
    keyfile=""
    for f in "$UTILS/keys/gpg-private.asc" "$UTILS/gpg-private.asc"; do
        [ -f "$f" ] && keyfile="$f" && break
    done

    if [ -n "$keyfile" ]; then
        gpg --batch --import "$keyfile"
        echo "  Imported from: $keyfile"
    else
        # Generate a new GPG key
        echo "  Generating new GPG keypair..."
        gpg --batch --gen-key <<EOF
Key-Type: RSA
Key-Length: 4096
Name-Real: $DOMAIN
Name-Email: admin@$DOMAIN
Expire-Date: 0
%no-protection
%commit
EOF
        # Export private key for backup
        gpg --armor --export-secret-keys "admin@$DOMAIN" > "$UTILS/keys/gpg-private.asc"
        echo "  Generated and saved to keys/gpg-private.asc"
        echo "  BACK UP THIS KEY — loss means you cannot re-sign files"
    fi
fi

# Export public key to web root
gpg --armor --export > "$HTDOCS/files/pubkey.asc" 2>/dev/null
echo "  Public key → $HTDOCS/files/pubkey.asc"
echo

# ── Passphrase ─────────────────────────────────────────────────────────────────
echo "--- Passphrase ---"
PP="$UTILS/passphrase.txt"
if [ -f "$PP" ] && [ -s "$PP" ]; then
    echo "  Already exists: $PP"
else
    sh "$UTILS/gen-passphrase.sh" > "$PP"
    chmod 600 "$PP"
    echo
    echo "  ╔══════════════════════════════════════════════════════════╗"
    echo "  ║  WRITE THIS DOWN — LOSS = PERMANENT DATA LOSS           ║"
    echo "  ╚══════════════════════════════════════════════════════════╝"
    echo
    cat "$PP"
    echo
fi
echo

echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. Copy source files into $UTILS/{html,pdf,docx,...}/"
echo "  2. Run: sh $UTILS/publish.sh"
