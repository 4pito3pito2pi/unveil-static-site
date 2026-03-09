#!/bin/sh
# setup-webserver.sh — install httpd + TLS for dpcpbp.org on OpenBSD 7.8
# Run as root. Review each step before running.
# Usage: sh setup-webserver.sh

set -e

DOMAIN="dpcpbp.org"
WEBROOT="/var/www/htdocs/${DOMAIN}"
SCRIPT_DIR="$(dirname "$0")"

echo "==> Creating web root directory"
mkdir -p "${WEBROOT}"
chown www:www "${WEBROOT}"

echo "==> Creating acme challenge directory"
mkdir -p /var/www/acme
chown www:www /var/www/acme

echo "==> Creating SSL key directory"
mkdir -p /etc/ssl/private
chmod 700 /etc/ssl/private

echo "==> Installing httpd.conf"
cp "${SCRIPT_DIR}/httpd.conf" /etc/httpd.conf
echo "    Review: cat /etc/httpd.conf"

echo "==> Installing acme-client.conf"
cp "${SCRIPT_DIR}/acme-client.conf" /etc/acme-client.conf
echo "    Review: cat /etc/acme-client.conf"

echo ""
echo "==> pf.conf — manual step required"
echo "    Add the following to /etc/pf.conf, then run: pfctl -f /etc/pf.conf"
echo ""
cat "${SCRIPT_DIR}/pf-web.snippet"
echo ""

echo "==> Placing sample index.html in web root"
cat > "${WEBROOT}/index.html" <<'HTML'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>dpcpbp.org</title></head>
<body>
<h1>dpcpbp.org</h1>
<p>Site coming soon.</p>
</body>
</html>
HTML

echo "==> Starting httpd (HTTP only, for acme challenge)"
rcctl enable httpd
rcctl start httpd || rcctl restart httpd

echo ""
echo "==> Requesting TLS certificate from Let's Encrypt"
echo "    (DNS must be pointing to this server before this works)"
echo ""
echo "    Run when ready: acme-client -v ${DOMAIN}"
echo ""
echo "==> After cert is issued, reload httpd to activate HTTPS:"
echo "    rcctl reload httpd"
echo ""
echo "==> Add cert renewal to root crontab (crontab -e):"
echo "    0 3 * * * acme-client ${DOMAIN} && rcctl reload httpd"
echo ""
echo "Done. Check /var/www/logs/access.log and /var/www/logs/error.log for logs."
