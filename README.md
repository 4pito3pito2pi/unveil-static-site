# unveil

Encrypted, GPG-signed static websites. No frameworks, no build tools, no JavaScript dependencies.

Drop files in a directory, run one command, get an encrypted site with client-side decryption, GPG signatures, and archiver-friendly manifests.

## What it does

- **AES-256-GCM encryption** with PBKDF2-SHA256 key derivation (260k iterations)
- **Client-side decryption** via Web Crypto API — works in any modern browser, no server-side processing
- **GPG signing** — every document is signed; signatures shown as footer in decrypted pages
- **Plaintext manifests** — `manifest.txt` and `manifest.html` list all documents with titles, SHA-256 hashes, and GPG signatures for web archiver authorship proof
- **Passphrase persistence** — optional sessionStorage/localStorage so you don't re-enter passphrase every page
- **Single-command management** — add, remove, rename files; everything rebuilds automatically

## Requirements

- Python 3 + `cryptography` module
- GPG (for signing)
- Any static web server, or none (S3, local file serving, etc.)

## Quick start

```sh
# 1. Configure
cp site.conf.example site.conf
vi site.conf              # set DOMAIN, paths, server type

# 2. Bootstrap (as root — installs deps, sets up server + TLS)
sh bootstrap.sh site.conf

# 3. Add files
cp *.html /path/to/utils/html/
cp *.pdf  /path/to/utils/pdf/

# 4. Publish
cd /path/to/utils
sh merge.sh
```

## Server support

Set `HTTPD=` in `site.conf`:

| Server | Value | TLS | Notes |
|--------|-------|-----|-------|
| OpenBSD httpd | `openbsd-httpd` | acme-client | Native OpenBSD |
| nginx | `nginx` | certbot | Debian, RHEL, Alpine, macOS |
| Apache | `apache` | certbot | Debian, RHEL, Alpine |
| Caddy | `caddy` | automatic | Zero-config TLS |
| None | `none` | — | S3, static hosting, DIY |

`bootstrap.sh` detects your OS, installs the server, generates the config, and sets up TLS — all from `site.conf`.

## Site management

```sh
sh merge.sh                           # process add/ queue + publish
sh merge.sh --publish                 # full republish
sh merge.sh --remove old-file.html    # remove a document
sh merge.sh --rename old.html new.html # rename everywhere
```

## Configuration

See `site.conf.example` for all options:

```sh
DOMAIN=example.com
UTILS_DIR=/var/www/utils/$DOMAIN
HTDOCS_DIR=/var/www/htdocs/$DOMAIN
HTTPD=nginx                     # openbsd-httpd | nginx | apache | caddy | none
TLS=acme                        # acme | none (caddy handles its own)
PASSPHRASE_WORDS=12
PBKDF2_ITERATIONS=260000
PASSPHRASE_PERSIST=session       # none | session | local
REVEAL=none                     # none | all
HASH_TREE=flat                  # flat | ternary
```

## Reveal mode

Reveal mode embeds the passphrase in the page so it auto-decrypts without prompting. The encryption and GPG signatures remain intact — useful for establishing authorship while making content publicly readable.

Three levels of control:

1. **Site-wide:** `REVEAL=all` in site.conf
2. **Per-directory:** put files in `html-public/` instead of `html/`
3. **Per-file:** list filenames in `utils/reveal.txt`, one per line

## URL token access

Any page supports `#key=<passphrase>` in the URL:

```
https://example.com/files/html/doc.html#key=my+secret+passphrase
```

The `#fragment` is never sent to the server. It is stripped from the URL bar after reading.

## Ternary hash tree

For sites with many files (500+), set `HASH_TREE=ternary` in site.conf. Files are distributed into a 3-way directory tree using SHA-256 hashes, keeping directory lookups O(1) on FFS/UFS.

```
Depth  Leaf dirs  Max files
  1        3         729
  2        9       2,187
  3       27       6,561
  4       81      19,683
```

## Offline decryption

```sh
python3 decrypt.py document.html              # decrypt HTML
python3 decrypt.py paper.pdf.enc -o paper.pdf  # decrypt binary
python3 decrypt.py --verify paper.pdf.enc      # verify GPG signature
```

## How encryption works

1. Source HTML encrypted with AES-256-GCM (random salt + IV per file)
2. Encrypted payload embedded in minimal HTML page with passphrase prompt
3. Browser decrypts using Web Crypto API — zero server involvement
4. Decrypted content renders via Blob URL
5. GPG signature injected as collapsible footer

Non-HTML files encrypted to `.enc` JSON with detached `.sig`.

## Stack

- POSIX shell
- Python 3 (standard library + cryptography)
- GPG
- Web Crypto API (browser-native, no JS libraries)

No Node. No npm. No webpack. No React. No Docker.
