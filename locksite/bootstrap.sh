#!/bin/sh
# bootstrap.sh — set up locksite from scratch on a fresh server
#
# Usage: sh bootstrap.sh [site.conf]
#
# Installs deps, creates dirs, configures web server + TLS, runs setup.

set -e

[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="${1:-$SCRIPT_DIR/site.conf}"
[ -f "$CONF" ] || { echo "Error: site.conf not found" >&2; exit 1; }
eval "$(grep -v '^#' "$CONF" | grep '=' | sed 's/\$DOMAIN/'$(grep '^DOMAIN=' "$CONF" | cut -d= -f2)'/g')"

echo "=== locksite bootstrap: $DOMAIN ==="
echo

# ── Dependencies ──────────────────────────────────────────────────────────
echo "--- Dependencies ---"
if [ "$(uname)" = "OpenBSD" ]; then
    for pkg in python3 gnupg; do
        which $pkg >/dev/null 2>&1 || pkg_add $pkg 2>/dev/null
    done
    python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" 2>/dev/null || \
        pkg_add py3-cryptography 2>/dev/null
elif [ -f /etc/debian_version ]; then
    apt-get install -y python3 python3-cryptography gnupg 2>/dev/null
fi
echo "  OK"
echo

# ── Copy scripts ─────────────────────────────────────────────────────────
echo "--- Installing scripts ---"
mkdir -p "$UTILS_DIR"
for f in locksite.py merge.sh setup.sh gen-passphrase.sh decrypt.py site.conf; do
    [ -f "$SCRIPT_DIR/$f" ] && cp "$SCRIPT_DIR/$f" "$UTILS_DIR/$f"
done
chmod +x "$UTILS_DIR"/*.sh 2>/dev/null || true
echo "  Scripts -> $UTILS_DIR/"
echo

# ── Web server ───────────────────────────────────────────────────────────
if [ "$HTTPD" = "openbsd-httpd" ] && [ ! -f "/etc/ssl/$DOMAIN.fullchain.pem" ]; then
    echo "--- Configuring httpd + TLS ---"

    grep -q "$DOMAIN" /etc/acme-client.conf 2>/dev/null || cat >> /etc/acme-client.conf <<ACME
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

    grep -q "$DOMAIN" /etc/httpd.conf 2>/dev/null || cat > /etc/httpd.conf <<HTTPD
server "$DOMAIN" {
	listen on * port 80
	alias "www.$DOMAIN"
	location "/.well-known/acme-challenge/*" { root "/acme"; request strip 2; }
	location "*" { block return 301 "https://\\\$HTTP_HOST\\\$REQUEST_URI" }
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

    rcctl enable httpd; rcctl restart httpd
    acme-client -v "$DOMAIN" && echo "  TLS: OK" || echo "  TLS: FAILED (check DNS)"
    (crontab -l 2>/dev/null; echo "0 3 * * * acme-client $DOMAIN && rcctl reload httpd") | sort -u | crontab -
    rcctl restart httpd
else
    echo "--- Web server: skipped (already configured or HTTPD=$HTTPD) ---"
fi
echo

# ── Run setup ────────────────────────────────────────────────────────────
sh "$UTILS_DIR/setup.sh"

echo
echo "Next: copy source files into $UTILS_DIR/{html,pdf,...}/"
echo "      or drop into $UTILS_DIR/add/"
echo "Then: cd $UTILS_DIR && sh merge.sh"
