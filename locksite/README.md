# locksite

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
- Any static web server (httpd, nginx, Apache, Caddy, S3, anything)

## Quick start

```sh
# 1. Edit site.conf
cp site.conf mysite.conf
vi mysite.conf              # set DOMAIN, paths

# 2. Bootstrap (as root, sets up dirs + GPG + passphrase + TLS)
sh bootstrap.sh mysite.conf

# 3. Add files
cp *.html /var/www/utils/example.com/html/
cp *.pdf  /var/www/utils/example.com/pdf/

# 4. Publish
cd /var/www/utils/example.com
sh merge.sh
```

## Site management

```sh
sh merge.sh                           # process add/ queue + publish
sh merge.sh --publish                 # full republish
sh merge.sh --remove old-file.html    # remove a document
sh merge.sh --rename old.html new.html # rename everywhere
```

## Configuration

Edit `site.conf`:

```sh
DOMAIN=example.com
UTILS_DIR=/var/www/utils/$DOMAIN        # source files + scripts
HTDOCS_DIR=/var/www/htdocs/$DOMAIN      # web root
PASSPHRASE_WORDS=12                     # passphrase length
PBKDF2_ITERATIONS=260000               # key derivation cost
PASSPHRASE_PERSIST=session              # none | session | local
REVEAL=none                            # none | all (see below)
HASH_TREE=flat                         # flat | ternary (see below)
HASH_TREE_DEPTH=4                      # 1-4 (ternary tree levels)
HTTPD=openbsd-httpd                     # openbsd-httpd | nginx | none
TLS=acme                               # acme | none
```

## Reveal mode

Reveal mode embeds the passphrase in the page so it auto-decrypts without prompting. The encryption and GPG signatures remain intact — useful for establishing authorship while making content publicly readable.

Three levels of control:

1. **Site-wide:** `REVEAL=all` in site.conf — every page auto-decrypts
2. **Per-directory:** put files in `html-public/` instead of `html/` (also `pdf-public/`, `public/`, etc.)
3. **Per-file:** list filenames in `utils/reveal.txt`, one per line

## URL token access

Any page supports `#key=<passphrase>` in the URL. The page auto-decrypts without prompting:

```
https://example.com/files/html/doc.html#key=my+secret+passphrase
```

The `#fragment` is never sent to the server — invisible in access logs and referrer headers. The fragment is stripped from the URL bar after reading. Falls back to `?key=` for compatibility (but `?key=` is visible in server logs).

Use this for selective subscriber access — distribute unique URLs per subscriber. If `PASSPHRASE_PERSIST` is set, the passphrase is also cached in the browser for subsequent pages.

## Ternary hash tree

For sites with many files (500+), OpenBSD FFS directory lookups slow down linearly (O(n) per lookup). The ternary hash tree distributes files into a 3-way directory structure using SHA-256 hashes of filenames.

Set `HASH_TREE=ternary` in site.conf. Each filename is hashed to a path like `1/0/2/0/filename.html`.

```
Depth  Leaf dirs  Max files (243/leaf)
  1        3            729
  2        9          2,187
  3       27          6,561
  4       81         19,683
```

No directory ever contains more than 243 files + 3 subdirs, keeping FFS lookups under 1ms. The original filename is preserved at the leaf — only the directory path is hashed. URLs remain clean: `/files/html/1/0/2/0/my-document.html`.

The hash tree is transparent to the index and manifest generators — all links are correct regardless of tree structure.

## Published site structure

```
index.html          encrypted document index
manifest.txt        plaintext manifest (titles, SHA-256, GPG sigs)
manifest.html       browseable manifest
files/
  index.html        encrypted file browser
  pubkey.asc        GPG public key
  html/             encrypted HTML documents (flat or ternary tree)
  pdf/              encrypted PDFs
  ...
```

## How encryption works

Each HTML page is a standalone encrypted document:
1. Source HTML is encrypted with AES-256-GCM (random salt + IV per file)
2. Encrypted payload is embedded in a minimal HTML page with a passphrase prompt
3. Browser decrypts using Web Crypto API (SubtleCrypto) — zero server involvement
4. Decrypted content renders via Blob URL with `<base>` tag for working relative links
5. GPG signature is injected as a collapsible footer in the decrypted page

Non-HTML files (PDF, DOCX, etc.) are encrypted to `.enc` JSON with detached `.sig` files.

## Stack

- POSIX shell
- Python 3 (standard library + cryptography)
- GPG
- Web Crypto API (browser-native, no JS libraries)

No Node. No npm. No webpack. No React. No Docker.
