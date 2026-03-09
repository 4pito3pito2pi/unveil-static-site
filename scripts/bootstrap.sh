#!/bin/sh
# bootstrap.sh — set up encrypted document site from scratch
#
# Run as root on a fresh OpenBSD server with httpd.
# Requires: python3, py3-cryptography, gnupg
#
# Usage:
#   sh bootstrap.sh <domain>           e.g. sh bootstrap.sh dpcpbp.org
#   sh bootstrap.sh <domain> --restore  Restore from backup tarball
#
# This script:
#   1. Installs dependencies (if missing)
#   2. Creates directory structure
#   3. Copies scripts into place
#   4. Configures httpd + ACME/TLS
#   5. Runs setup.sh (GPG key + passphrase)
#
# After bootstrap, add source files and run:
#   cd /var/www/utils/<domain> && sh merge.sh

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root." >&2
    exit 1
fi

DOMAIN="${1:?Usage: sh bootstrap.sh <domain>}"
UTILS="/var/www/utils/$DOMAIN"
HTDOCS="/var/www/htdocs/$DOMAIN"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Bootstrap: $DOMAIN ==="
echo

# ── 1. Dependencies ───────────────────────────────────────────────────────────
echo "--- Checking dependencies ---"
for pkg in python3 gnupg; do
    if ! which $pkg >/dev/null 2>&1; then
        echo "  Installing $pkg..."
        pkg_add $pkg 2>/dev/null || true
    else
        echo "  $pkg: OK"
    fi
done
# py3-cryptography
python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" 2>/dev/null || {
    echo "  Installing py3-cryptography..."
    pkg_add py3-cryptography 2>/dev/null || pip3 install cryptography
}
echo

# ── 2. Directory structure ────────────────────────────────────────────────────
echo "--- Creating directories ---"
mkdir -p "$UTILS"/{html,pdf,docx,txt,add,keys,misc}
mkdir -p "$HTDOCS"/files/{html,pdf,docx,txt,misc}
echo "  $UTILS/"
echo "  $HTDOCS/"
echo

# ── 3. Copy scripts ──────────────────────────────────────────────────────────
echo "--- Installing scripts ---"
for f in encrypt-html.py gen-site-index.py gen-passphrase.sh \
         merge.sh publish.sh setup.sh decrypt.py verify-html.sh \
         DECRYPT-README.txt rename-files.sh; do
    src="$SCRIPTS_DIR/$f"
    if [ -f "$src" ]; then
        cp "$src" "$UTILS/$f"
        echo "  $f"
    fi
done
chmod +x "$UTILS"/*.sh 2>/dev/null || true
echo

# ── 4. ACME + TLS (if not already configured) ────────────────────────────────
if [ ! -f "/etc/ssl/$DOMAIN.fullchain.pem" ]; then
    echo "--- Configuring ACME/TLS ---"

    # acme-client.conf
    if ! grep -q "$DOMAIN" /etc/acme-client.conf 2>/dev/null; then
        cat >> /etc/acme-client.conf <<ACME
authority letsencrypt {
    api url "https://acme-v02.api.letsencrypt.org/directory"
    account key "/etc/acme/letsencrypt-privkey.pem"
}

domain $DOMAIN {
    alternative names { www.$DOMAIN }
    domain key "/etc/ssl/private/$DOMAIN.key"
    domain full chain certificate "/etc/ssl/$DOMAIN.fullchain.pem"
    sign with letsencrypt
}
ACME
        echo "  acme-client.conf: updated"
    fi

    # httpd.conf (minimal, HTTP-only for initial cert)
    if ! grep -q "$DOMAIN" /etc/httpd.conf 2>/dev/null; then
        cat > /etc/httpd.conf <<HTTPD
server "$DOMAIN" {
	listen on * port 80
	alias "www.$DOMAIN"
	location "/.well-known/acme-challenge/*" {
		root "/acme"
		request strip 2
	}
	location "*" {
		block return 301 "https://\\\$HTTP_HOST\\\$REQUEST_URI"
	}
}

server "$DOMAIN" {
	listen on * tls port 443
	alias "www.$DOMAIN"
	tls {
		certificate "/etc/ssl/$DOMAIN.fullchain.pem"
		key "/etc/ssl/private/$DOMAIN.key"
	}
	root "/htdocs/$DOMAIN"
	directory index "index.html"
	connection max request body 209715200
	location "*" { pass }
}
HTTPD
        echo "  httpd.conf: written"
    fi

    # Get initial cert
    rcctl enable httpd
    rcctl restart httpd
    acme-client -v "$DOMAIN" && echo "  TLS cert: obtained" || echo "  TLS cert: FAILED (check DNS)"

    # Add cron for renewal
    (crontab -l 2>/dev/null; echo "0 3 * * * acme-client $DOMAIN && rcctl reload httpd") | sort -u | crontab -
    echo "  cron: daily renewal at 3am"

    rcctl restart httpd
else
    echo "--- TLS already configured ---"
fi
echo

# ── 5. Run setup (GPG key + passphrase) ──────────────────────────────────────
echo "--- Running setup ---"
sh "$UTILS/setup.sh"
echo

echo "=== Bootstrap complete ==="
echo
echo "Next steps:"
echo "  1. Copy source files into $UTILS/{html,pdf,docx,txt}/"
echo "     or drop into $UTILS/add/ for auto-sorting"
echo "  2. Run: cd $UTILS && sh merge.sh"
echo "  3. Site will be live at https://$DOMAIN/"
echo "  4. Manifest at https://$DOMAIN/manifest.txt"
