#!/bin/sh
# verify-html.sh — verify the embedded GPG signature of an encrypted HTML file
#
# Usage: verify-html.sh <file.html>
#
# Extracts the ciphertext JSON payload and the armored GPG signature from
# the HTML, then runs gpg --verify. Requires gpg and python3.

set -e

[ -z "$1" ] && { echo "Usage: verify-html.sh <file.html>" >&2; exit 1; }
[ -f "$1" ] || { echo "File not found: $1" >&2; exit 1; }

python3 - "$1" << 'PYEOF'
import sys, re
html = open(sys.argv[1]).read()

m_json = re.search(r'<pre id="enc-data"[^>]*>(.*?)</pre>', html, re.S)
m_sig  = re.search(r'<pre class="armor">(.*?)</pre>',      html, re.S)

if not m_json:
    print("ERROR: no enc-data block found — is this an encrypted HTML file?", file=sys.stderr)
    sys.exit(1)
if not m_sig:
    print("ERROR: no GPG signature block found — file was not signed with --sign", file=sys.stderr)
    sys.exit(1)

open('/tmp/_verify_payload.json', 'w').write(m_json.group(1).strip())
open('/tmp/_verify_payload.sig',  'w').write(m_sig.group(1).strip())
PYEOF

gpg --verify /tmp/_verify_payload.sig /tmp/_verify_payload.json
