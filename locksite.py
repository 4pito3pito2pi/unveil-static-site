#!/usr/bin/env python3
"""
unveil (locksite) — encrypt, sign, and publish a static website

Reads site.conf for configuration. All paths are configurable.

Usage:
  locksite.py encrypt                 Encrypt all source files
  locksite.py index                   Rebuild indexes and manifests
  locksite.py publish                 Encrypt + index (full publish)
  locksite.py rollback                Restore previous publish snapshot
  locksite.py snapshots               List available snapshots
  locksite.py encrypt-file <f> <out>  Encrypt a single file
  locksite.py test                    Round-trip self-test
"""

import sys
import os
import re
import json
import base64
import hashlib
import getpass
import subprocess
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT_LEN = 32
IV_LEN   = 12
HTML_EXTENSIONS = {".html", ".htm"}
SKIP_DIRS = {"add", "keys", "__pycache__", ".git"}
SKIP_EXTS = {".sh", ".py", ".tgz", ".asc", ".sig", ".conf"}
REVEAL_DIRS = {"html-public", "pdf-public", "docx-public", "txt-public", "public"}

# ── Ternary hash tree ─────────────────────────────────────────────────────────
# Maps filenames to a 4-level directory tree using base-3 digits of SHA-256.
# Each level has 3 subdirs (0, 1, 2). 4 levels = 81 leaf dirs.
# Max 243 files per leaf = 19,683 files per site.
# Tree depth is configurable (1-4). Capacity = 3^depth * 243.

HASH_TREE_MAX_LEAF = 243  # max files per terminal directory

def ternary_path(filename: str, depth: int = 4) -> str:
    """Return ternary hash path prefix for a filename (e.g. '1/0/2/0')."""
    h = hashlib.sha256(filename.encode()).digest()
    # Convert first bytes to base-3 digits
    n = int.from_bytes(h[:8], "big")
    digits = []
    for _ in range(depth):
        digits.append(str(n % 3))
        n //= 3
    return "/".join(digits)

def flat_to_tree_path(filename: str, depth: int) -> Path:
    """Return the tree-relative path for a file: e.g. '1/0/2/0/filename.html'."""
    if depth == 0:
        return Path(filename)
    return Path(ternary_path(filename, depth)) / filename


def should_reveal(filename: str, source_dir: str, conf: dict) -> bool:
    """Determine if a file should be revealed (auto-decrypt, no passphrase prompt).

    Three levels of control:
      1. site.conf REVEAL=all — entire site is revealed
      2. Per-directory — files in public/ or html-public/ dirs are revealed
      3. Per-file — filenames listed in utils/reveal.txt are revealed
    """
    if conf.get("REVEAL", "none") == "all":
        return True
    if source_dir in REVEAL_DIRS:
        return True
    reveal_file = Path(conf["UTILS_DIR"]) / "reveal.txt"
    if reveal_file.exists():
        revealed = {l.strip() for l in reveal_file.read_text().splitlines()
                    if l.strip() and not l.startswith("#")}
        if filename in revealed:
            return True
    return False


# ── Config ─────────────────────────────────────────────────────────────────────

def load_conf(conf_path: Path = None) -> dict:
    """Load site.conf — simple KEY=VALUE format, shell-style."""
    conf = {
        "DOMAIN": "",
        "UTILS_DIR": "",
        "HTDOCS_DIR": "",
        "PASSPHRASE_WORDS": "12",
        "PBKDF2_ITERATIONS": "260000",
        "GPG_EMAIL": "",
        "HTTPD": "openbsd-httpd",
        "TLS": "acme",
        "PASSPHRASE_PERSIST": "session",
        "REVEAL": "none",
        "HASH_TREE": "flat",
        "HASH_TREE_DEPTH": "4",
    }
    if conf_path is None:
        for candidate in [Path("site.conf"), Path(__file__).parent / "site.conf"]:
            if candidate.exists():
                conf_path = candidate
                break
    if conf_path and conf_path.exists():
        for line in conf_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
    # Expand $DOMAIN in paths
    domain = conf["DOMAIN"]
    for k in ("UTILS_DIR", "HTDOCS_DIR", "GPG_EMAIL"):
        conf[k] = conf[k].replace("$DOMAIN", domain)
    conf["PBKDF2_ITERATIONS"] = int(conf["PBKDF2_ITERATIONS"])
    conf["HASH_TREE_DEPTH"] = int(conf["HASH_TREE_DEPTH"])
    return conf


# ── Crypto ─────────────────────────────────────────────────────────────────────

def derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt(plaintext: bytes, passphrase: str, iterations: int) -> dict:
    salt = os.urandom(SALT_LEN)
    iv   = os.urandom(IV_LEN)
    key  = derive_key(passphrase, salt, iterations)
    ct   = AESGCM(key).encrypt(iv, plaintext, None)
    return {
        "salt": base64.urlsafe_b64encode(salt).decode(),
        "iv":   base64.urlsafe_b64encode(iv).decode(),
        "ct":   base64.urlsafe_b64encode(ct).decode(),
        "iter": iterations,
    }


def decrypt(enc: dict, passphrase: str) -> bytes:
    salt = base64.urlsafe_b64decode(enc["salt"])
    iv   = base64.urlsafe_b64decode(enc["iv"])
    ct   = base64.urlsafe_b64decode(enc["ct"])
    key  = derive_key(passphrase, salt, int(enc.get("iter", 260000)))
    return AESGCM(key).decrypt(iv, ct, None)


# ── HTML helpers ───────────────────────────────────────────────────────────────

class TitleExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = ""
    def handle_starttag(self, tag, attrs):
        if tag == "title": self._in_title = True
    def handle_endtag(self, tag):
        if tag == "title": self._in_title = False
    def handle_data(self, data):
        if self._in_title: self.title += data


GENERIC_TITLES = {"google", "untitled", "untitled document", "new tab",
                  "encrypted document", "document", "", "home"}
STRIP_PREFIXES = ["Wolfram - ", "Google - "]


def clean_title(title: str) -> str:
    for prefix in STRIP_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):]
            break
    return title

def extract_title(html: str, fallback: str = "Encrypted Document") -> str:
    p = TitleExtractor()
    p.feed(html)
    title = p.title.strip()
    if not title or title.lower() in GENERIC_TITLES:
        return fallback
    return clean_title(title)


# ── GPG signing ────────────────────────────────────────────────────────────────

def gpg_sign_data(data: bytes) -> str | None:
    result = subprocess.run(
        ["gpg", "--batch", "--yes", "--detach-sign", "--armor"],
        input=data, capture_output=True)
    if result.returncode != 0:
        print(f"  GPG sign failed: {result.stderr.decode().strip()}", file=sys.stderr)
        return None
    return result.stdout.decode()


def get_gpg_fingerprint() -> str:
    try:
        r = subprocess.run(["gpg", "--list-keys", "--with-colons"],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith("fpr:"):
                return line.split(":")[9]
    except Exception:
        pass
    return "unknown"


# ── HTML wrapper ───────────────────────────────────────────────────────────────

def wrap_html_encrypted(enc: dict, title: str, source_filename: str,
                        sig_armor: str = None, persist: str = "session",
                        reveal: str = None) -> str:
    enc_json = json.dumps(enc)

    # Storage API for passphrase persistence
    if persist == "local":
        storage_js = "localStorage"
    elif persist == "session":
        storage_js = "sessionStorage"
    else:
        storage_js = ""

    # URL token support: #key=passphrase (fragment — never sent to server)
    # Falls back to ?key= for compatibility
    url_key_js = (
        'const _h = window.location.hash.slice(1);'
        'const _hp = new URLSearchParams(_h);'
        'const urlKey = _hp.get("key") || new URLSearchParams(window.location.search).get("key");'
        'if (urlKey && window.location.hash) { history.replaceState(null, "", window.location.pathname); }'
    )

    # Passphrase persistence JS
    if reveal:
        # Reveal mode: embed passphrase, auto-decrypt on load, hide prompt
        save_pw = ""
        load_pw = f'document.getElementById("pw").value = "{reveal}";'
        auto_unlock = 'document.querySelector(".box").style.display="none"; unlock();'
    elif storage_js:
        save_pw = f'{storage_js}.setItem("locksite_pw", pw);'
        load_pw = (
            f'document.getElementById("pw").value = urlKey || '
            f'{storage_js}.getItem("locksite_pw") || "";'
        )
        auto_unlock = (
            f'if (urlKey) {{ document.querySelector(".box").style.display="none"; unlock(); }}'
            f' else if ({storage_js}.getItem("locksite_pw")) {{ unlock(); }}'
        )
    else:
        save_pw = ""
        load_pw = 'document.getElementById("pw").value = urlKey || "";'
        auto_unlock = 'if (urlKey) { document.querySelector(".box").style.display="none"; unlock(); }'

    # GPG sig — embedded in the encrypted payload so it shows AFTER decryption
    # We inject it into the decrypted HTML as a footer
    if sig_armor:
        sig_inject_js = (
            "const sigFooter = document.createElement('div');"
            "sigFooter.style.cssText = 'margin:2rem 0;padding:1rem;border-top:1px solid #333;"
            "font-family:monospace;font-size:0.7rem;color:#555;';"
            "const det = document.createElement('details');"
            "det.innerHTML = '<summary style=\"cursor:pointer;color:#666\">GPG Signature</summary>"
            "<pre style=\"white-space:pre-wrap;word-break:break-all;color:#444;margin:0.5rem 0\">"
            + sig_armor.strip().replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            + "</pre>';"
            "sigFooter.appendChild(det);"
        )
    else:
        sig_inject_js = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="encryption" content="AES-256-GCM/PBKDF2-SHA256/{enc['iter']}">
  <meta name="source" content="{source_filename}">
  <title>{title} [encrypted]</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: sans-serif; background: #111; color: #ccc;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; }}
    .box {{ text-align: center; max-width: 380px; width: 100%; padding: 2rem; }}
    h2 {{ font-size: 1rem; color: #888; font-weight: normal; margin: 0 0 1.5rem; }}
    .title {{ font-size: 1.1rem; color: #ddd; margin-bottom: 0.4rem; }}
    input[type=text] {{
      width: 100%; padding: 0.6rem 0.8rem; font-size: 1rem;
      background: #1e1e1e; border: 1px solid #333; border-radius: 5px;
      color: #eee; outline: none; margin-bottom: 0.8rem;
    }}
    input[type=text]:focus {{ border-color: #555; }}
    button {{
      width: 100%; padding: 0.6rem; font-size: 1rem; cursor: pointer;
      background: #2a2a2a; border: 1px solid #444; border-radius: 5px;
      color: #ccc; transition: background 0.15s;
    }}
    button:hover {{ background: #333; }}
    button:disabled {{ opacity: 0.5; cursor: default; }}
    .err {{ color: #e06c75; font-size: 0.85rem; margin-top: 0.8rem; min-height: 1.2em; }}
    .spin {{ display: none; margin-top: 0.8rem; color: #666; font-size: 0.85rem; }}
  </style>
</head>
<body>
<div class="box">
  <div class="title">{title}</div>
  <h2>This document is encrypted</h2>
  <input type="text" id="pw" placeholder="Passphrase" autofocus autocomplete="off" spellcheck="false">
  <button id="btn" onclick="unlock()">Unlock</button>
  <div class="spin" id="spin">Decrypting&hellip;</div>
  <div class="err" id="err"></div>
</div>
<pre id="enc-data" style="display:none" aria-hidden="true">{enc_json}</pre>
<script>
{url_key_js}
{load_pw}
document.getElementById('pw').addEventListener('keydown', e => {{
  if (e.key === 'Enter') unlock();
}});
async function unlock() {{
  const pw   = document.getElementById('pw').value;
  const btn  = document.getElementById('btn');
  const err  = document.getElementById('err');
  const spin = document.getElementById('spin');
  if (!pw) {{ err.textContent = 'Enter a passphrase.'; return; }}
  btn.disabled = true;
  err.textContent = '';
  spin.style.display = 'block';
  const enc = JSON.parse(document.getElementById('enc-data').textContent);
  const b64 = s => {{
    s = s.trim().replace(/\\s+/g, '').replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(s), c => c.charCodeAt(0));
  }};
  try {{
    const te  = new TextEncoder();
    const raw = await crypto.subtle.importKey('raw', te.encode(pw), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey(
      {{ name: 'PBKDF2', salt: b64(enc.salt), iterations: parseInt(enc.iter) || 260000, hash: 'SHA-256' }},
      raw, {{ name: 'AES-GCM', length: 256 }}, false, ['decrypt']
    );
    const plain = await crypto.subtle.decrypt({{ name: 'AES-GCM', iv: b64(enc.iv) }}, key, b64(enc.ct));
    {save_pw}
    let html = new TextDecoder().decode(plain);
    const base = location.origin + location.pathname.replace(/[^/]*$/, '');
    html = html.replace(/<head([^>]*)>/i, '<head$1><base href="' + base + '">');
    // Inject GPG signature footer into decrypted content
    {sig_inject_js}
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    {"doc.body.appendChild(sigFooter);" if sig_armor else ""}
    html = doc.documentElement.outerHTML;
    const blob = new Blob([html], {{type: 'text/html'}});
    location.href = URL.createObjectURL(blob);
  }} catch (_) {{
    spin.style.display = 'none';
    btn.disabled = false;
    err.textContent = 'Wrong passphrase or corrupted data.';
    document.getElementById('pw').select();
  }}
}}
{auto_unlock}
</script>
</body>
</html>
"""


# ── Encrypt operations ─────────────────────────────────────────────────────────

def needs_update(src: Path, dest: Path) -> bool:
    return not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime


def encrypt_html_file(src, dest, passphrase, iterations, persist,
                      sign=True, reveal=None):
    if not needs_update(src, dest):
        return False
    data = src.read_bytes()
    # Use filename (without extension) as fallback for generic titles like "Google"
    fallback = src.stem.replace("-", " ").replace("_", " ")
    title = extract_title(data.decode("utf-8", errors="replace"), fallback)
    enc = encrypt(data, passphrase, iterations)
    sig_armor = gpg_sign_data(json.dumps(enc).encode()) if sign else None
    wrapped = wrap_html_encrypted(enc, title, src.name, sig_armor, persist,
                                  reveal=reveal)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(wrapped)
    return True


def encrypt_binary_file(src, dest_enc, dest_sig, passphrase, iterations, sign=True):
    if not needs_update(src, dest_enc):
        return False
    data = src.read_bytes()
    enc = encrypt(data, passphrase, iterations)
    enc["filename"] = src.name
    enc_json = json.dumps(enc, indent=2)
    dest_enc.parent.mkdir(parents=True, exist_ok=True)
    dest_enc.write_text(enc_json)
    if sign:
        sig_armor = gpg_sign_data(enc_json.encode())
        if sig_armor:
            dest_sig.write_text(sig_armor)
    return True


def cmd_encrypt(conf):
    utils_dir  = Path(conf["UTILS_DIR"])
    htdocs_dir = Path(conf["HTDOCS_DIR"])
    files_dir  = htdocs_dir / "files"
    iterations = conf["PBKDF2_ITERATIONS"]
    persist    = conf.get("PASSPHRASE_PERSIST", "session")
    use_tree   = conf.get("HASH_TREE", "flat") == "ternary"
    tree_depth = conf.get("HASH_TREE_DEPTH", 4)

    pp_file = utils_dir / "passphrase.txt"
    if not pp_file.exists() or not pp_file.stat().st_size:
        print(f"Error: passphrase not found: {pp_file}", file=sys.stderr)
        sys.exit(1)
    passphrase = pp_file.read_text().strip()

    files_dir.mkdir(parents=True, exist_ok=True)
    if use_tree:
        print(f"  Hash tree: ternary, depth={tree_depth}, "
              f"capacity={3**tree_depth * HASH_TREE_MAX_LEAF}")

    html_count = html_updated = bin_count = bin_updated = 0

    for subdir in sorted(utils_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if subdir.name in SKIP_DIRS or subdir.name.startswith("."):
            continue

        for src in sorted(subdir.rglob("*")):
            if not src.is_file() or src.suffix.lower() in SKIP_EXTS:
                continue

            rel = src.relative_to(utils_dir)

            # Determine output path: flat or ternary tree
            if use_tree:
                tree_rel = flat_to_tree_path(src.name, tree_depth)
                dest_base = files_dir / rel.parts[0] / tree_rel
            else:
                dest_base = files_dir / rel
            dest_base.parent.mkdir(parents=True, exist_ok=True)

            if src.suffix.lower() in HTML_EXTENSIONS:
                html_count += 1
                reveal_pw = passphrase if should_reveal(src.name, subdir.name, conf) else None
                tag = "reveal" if reveal_pw else "html"
                if encrypt_html_file(src, dest_base,
                                     passphrase, iterations, persist,
                                     reveal=reveal_pw):
                    html_updated += 1
                    print(f"  [{tag}] {rel}")
            else:
                bin_count += 1
                enc_path = dest_base.parent / (src.name + ".enc")
                sig_path = dest_base.parent / (src.name + ".enc.sig")
                if encrypt_binary_file(src, enc_path, sig_path,
                                       passphrase, iterations):
                    bin_updated += 1
                    print(f"  [enc]  {rel}")

    print(f"\n  HTML: {html_updated}/{html_count}, Other: {bin_updated}/{bin_count}")


# ── Index + manifest generation ────────────────────────────────────────────────

def extract_encrypted_title(html: str, fallback: str) -> str:
    m = re.search(r'<title>(.*?)\s*\[encrypted\]</title>', html, re.I)
    title = m.group(1).strip() if m else None
    if not title:
        m = re.search(r'<title>(.*?)</title>', html, re.I)
        title = m.group(1).strip() if m else None
    if not title or title.lower() in GENERIC_TITLES:
        return fallback.replace("-", " ").replace("_", " ")
    return clean_title(title)


def extract_gpg_sig(html: str) -> str:
    m = re.search(r'(-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----)', html, re.S)
    return m.group(1).strip() if m else ""


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def cmd_index(conf):
    domain     = conf["DOMAIN"]
    utils_dir  = Path(conf["UTILS_DIR"])
    htdocs_dir = Path(conf["HTDOCS_DIR"])
    files_dir  = htdocs_dir / "files"
    files_html = files_dir / "html"
    iterations = conf["PBKDF2_ITERATIONS"]
    persist    = conf.get("PASSPHRASE_PERSIST", "session")
    use_tree   = conf.get("HASH_TREE", "flat") == "ternary"

    pp_file = utils_dir / "passphrase.txt"
    if not pp_file.exists() or not pp_file.stat().st_size:
        print(f"Error: passphrase not found: {pp_file}", file=sys.stderr)
        sys.exit(1)
    passphrase = pp_file.read_text().strip()

    if not files_html.is_dir():
        print(f"No files/html/ directory: {files_html}", file=sys.stderr)
        sys.exit(1)

    # Collect document items — walk tree or flat, deduplicate by filename
    seen = {}
    for f in files_html.rglob("*"):
        if f.is_file() and f.suffix.lower() in HTML_EXTENSIONS:
            if f.name in seen:
                continue  # skip duplicates (e.g. flat + tree coexist)
            title = extract_encrypted_title(f.read_text(errors="replace"), f.stem)
            href = "files/html/" + str(f.relative_to(files_html))
            seen[f.name] = (f.name, title, href)
    items = sorted(seen.values(), key=lambda x: x[1].lower())  # sort by title

    print(f"  Building index: {len(items)} documents")

    # ── Root index.html ───────────────────────────────────────────────────
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    links = "\n".join(f'<li><a href="{h}">{t}</a></li>' for _, t, h in items)
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{domain}</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #ccc;
       max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
.hdr {{ display: flex; justify-content: space-between; align-items: baseline;
        border-bottom: 1px solid #222; padding-bottom: 0.8rem; margin-bottom: 1.2rem; }}
h1 {{ font-size: 1rem; color: #888; font-weight: normal; margin: 0; }}
a.fl {{ font-size: 0.85rem; color: #7aa2c8; text-decoration: none; }}
ul {{ list-style: none; padding: 0; margin: 0; column-count: 2; column-gap: 2rem; }}
li {{ padding: 0.15rem 0; font-size: 0.85rem; break-inside: avoid; }}
li a {{ color: #aaa; text-decoration: none; }}
li a:hover {{ color: #ddd; }}
.ft {{ margin-top: 2rem; font-size: 0.75rem; color: #333;
       border-top: 1px solid #1a1a1a; padding-top: 0.8rem; }}
</style></head><body>
<div class="hdr"><h1>{domain} &mdash; {len(items)} documents</h1>
<a class="fl" href="files/">Files &rarr;</a></div>
<ul>{links}</ul>
<p class="ft">Generated {generated} &middot; <a href="manifest.html" style="color:#555">manifest</a>
&middot; <a href="files/pubkey.asc" style="color:#333">pubkey.asc</a></p>
</body></html>"""

    enc = encrypt(index_html.encode(), passphrase, iterations)
    sig = gpg_sign_data(json.dumps(enc).encode())
    wrapped = wrap_html_encrypted(enc, domain, "index.html", sig, persist)
    (htdocs_dir / "index.html").write_text(wrapped)
    print(f"  index.html")

    # ── files/index.html ──────────────────────────────────────────────────
    sections = {}
    for p in sorted(files_dir.rglob("*")):
        if not p.is_file(): continue
        rel = p.relative_to(files_dir)
        if str(rel) == "index.html": continue
        parts = rel.parts
        if parts[0] in SKIP_DIRS: continue
        section = parts[0] if len(parts) > 1 else "."
        sections.setdefault(section, []).append((str(rel), p.name, p.stat().st_size))

    total = sum(len(v) for v in sections.values())
    sec_html = []
    for sn in sorted(sections):
        files = sections[sn]
        label = sn if sn != "." else "root"
        rows = "\n".join(
            f'<tr><td><a href="{r}">{n}</a></td><td class="sz">{human_size(s)}</td></tr>'
            for r, n, s in sorted(files, key=lambda x: x[1].lower()))
        sec_html.append(f'<h2>{label}/ ({len(files)})</h2>\n<table>{rows}</table>')

    files_page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>{domain} — files</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #ccc;
       max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1rem; color: #888; font-weight: normal; border-bottom: 1px solid #222; padding-bottom: 0.8rem; }}
h1 a {{ color: #7aa2c8; text-decoration: none; font-size: 0.85rem; margin-left: 1rem; }}
h2 {{ font-size: 0.9rem; color: #777; margin: 1.5rem 0 0.5rem; }}
table {{ width: 100%; border-collapse: collapse; }}
tr:hover {{ background: #1a1a1a; }}
td {{ padding: 0.2rem 0.4rem; font-size: 0.82rem; }}
td a {{ color: #aaa; text-decoration: none; }}
td a:hover {{ color: #ddd; }}
td.sz {{ color: #555; text-align: right; white-space: nowrap; width: 5rem; }}
</style></head><body>
<h1>{domain} — {total} files <a href="/">&larr; Index</a></h1>
{"".join(sec_html)}
</body></html>"""

    fenc = encrypt(files_page.encode(), passphrase, iterations)
    fsig = gpg_sign_data(json.dumps(fenc).encode())
    fwrapped = wrap_html_encrypted(fenc, f"{domain} — files", "files/index.html", fsig, persist)
    (files_dir / "index.html").write_text(fwrapped)
    print(f"  files/index.html")

    # ── Manifests (unencrypted — for web archivers) ───────────────────────
    fingerprint = get_gpg_fingerprint()
    gen_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # manifest.txt
    lines = [f"MANIFEST — {domain}", f"Generated: {gen_time}",
             f"GPG Fingerprint: {fingerprint}",
             f"Public Key: https://{domain}/files/pubkey.asc",
             f"Documents: {len(items)}", "", "-" * 80, ""]
    for filename, title, href in items:
        ep = htdocs_dir / href
        sha = hashlib.sha256(ep.read_bytes()).hexdigest() if ep.exists() else ""
        gsig = extract_gpg_sig(ep.read_text(errors="replace")) if ep.exists() else ""
        lines += [f"Title:    {title}", f"File:     {filename}",
                  f"URL:      https://{domain}/{href}", f"SHA-256:  {sha}"]
        if gsig: lines.append(f"GPG Sig:  {gsig}")
        lines.append("")
    (htdocs_dir / "manifest.txt").write_text("\n".join(lines))
    print(f"  manifest.txt")

    # manifest.html
    rows = []
    for filename, title, href in items:
        ep = htdocs_dir / href
        sha = hashlib.sha256(ep.read_bytes()).hexdigest()[:16] + "..." if ep.exists() else ""
        rows.append(f'<tr><td class="t">{title}</td>'
                    f'<td><a href="{href}">{filename}</a></td>'
                    f'<td class="h">{sha}</td></tr>')
    manifest_page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>{domain} — Manifest</title>
<style>
body {{ font-family: monospace; background: #111; color: #ccc;
       max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1rem; color: #888; font-weight: normal; border-bottom: 1px solid #222; padding-bottom: 0.8rem; }}
.meta {{ font-size: 0.8rem; color: #555; margin-bottom: 1.5rem; }}
.meta a {{ color: #7aa2c8; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; }}
th {{ text-align: left; color: #555; border-bottom: 1px solid #222; padding: 0.3rem 0.4rem; font-weight: normal; }}
td {{ padding: 0.2rem 0.4rem; border-bottom: 1px solid #1a1a1a; }}
td.t {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
td.h {{ color: #555; font-size: 0.7rem; }}
td a {{ color: #aaa; text-decoration: none; }}
</style></head><body>
<h1>{domain} — Manifest ({len(items)} documents)</h1>
<div class="meta">Generated: {gen_time}<br>
GPG Fingerprint: <code>{fingerprint}</code><br>
<a href="files/pubkey.asc">pubkey.asc</a> | <a href="manifest.txt">manifest.txt</a></div>
<table><tr><th>Title</th><th>File</th><th>SHA-256</th></tr>
{"".join(rows)}</table>
</body></html>"""
    (htdocs_dir / "manifest.html").write_text(manifest_page)
    print(f"  manifest.html")


# ── Test ───────────────────────────────────────────────────────────────────────

def run_test():
    print("=== locksite round-trip test ===")
    pp = "correct horse battery staple test"
    data = b"<html><head><title>Test</title></head><body>Secret: 42</body></html>"
    enc = encrypt(data, pp, 260000)
    assert b"Secret: 42" in decrypt(enc, pp)
    print("  HTML: OK")
    bindata = b"\x00\x01\xff" * 100
    enc2 = encrypt(bindata, pp, 260000)
    assert decrypt(enc2, pp) == bindata
    print("  Binary: OK")
    print("=== passed ===")


# ── Snapshots / rollback ───────────────────────────────────────────────────────

MAX_SNAPSHOTS = 5  # keep last N snapshots

def snapshot_dir(conf) -> Path:
    return Path(conf["UTILS_DIR"]) / ".snapshots"

def create_snapshot(conf):
    """Snapshot htdocs before publishing. Uses hardlinks for efficiency."""
    import shutil
    htdocs = Path(conf["HTDOCS_DIR"])
    if not htdocs.exists():
        return
    sdir = snapshot_dir(conf)
    sdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dest = sdir / stamp
    shutil.copytree(htdocs, dest, copy_function=os.link)
    print(f"  Snapshot: {stamp}")
    # Prune old snapshots
    snaps = sorted(sdir.iterdir())
    while len(snaps) > MAX_SNAPSHOTS:
        old = snaps.pop(0)
        shutil.rmtree(old)
        print(f"  Pruned: {old.name}")

def cmd_rollback(conf):
    """Restore the most recent snapshot."""
    import shutil
    sdir = snapshot_dir(conf)
    htdocs = Path(conf["HTDOCS_DIR"])
    if not sdir.exists():
        print("No snapshots found.", file=sys.stderr)
        sys.exit(1)
    snaps = sorted(sdir.iterdir())
    if not snaps:
        print("No snapshots found.", file=sys.stderr)
        sys.exit(1)
    latest = snaps[-1]
    print(f"Rolling back to snapshot: {latest.name}")
    # Remove current htdocs and replace with snapshot
    if htdocs.exists():
        shutil.rmtree(htdocs)
    shutil.copytree(latest, htdocs)
    # Remove the used snapshot
    shutil.rmtree(latest)
    print(f"Rollback complete. Site restored to {latest.name}")

def cmd_snapshots(conf):
    """List available snapshots."""
    sdir = snapshot_dir(conf)
    if not sdir.exists():
        print("No snapshots.")
        return
    snaps = sorted(sdir.iterdir())
    if not snaps:
        print("No snapshots.")
        return
    print(f"Available snapshots ({len(snaps)}):")
    for s in snaps:
        # Count files in snapshot
        n = sum(1 for _ in s.rglob("*") if _.is_file())
        print(f"  {s.name}  ({n} files)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "test":
        run_test()
        return

    conf = load_conf()
    if not conf["DOMAIN"]:
        print("Error: set DOMAIN in site.conf", file=sys.stderr)
        sys.exit(1)

    if cmd == "encrypt":
        cmd_encrypt(conf)
    elif cmd == "index":
        cmd_index(conf)
    elif cmd == "publish":
        print(f"=== {conf['DOMAIN']} — publish ===\n")
        print("--- Snapshot ---")
        create_snapshot(conf)
        print("\n--- Encrypting ---")
        cmd_encrypt(conf)
        print("\n--- Building indexes + manifests ---")
        cmd_index(conf)
        print(f"\n=== Done ===")
    elif cmd == "rollback":
        cmd_rollback(conf)
    elif cmd == "snapshots":
        cmd_snapshots(conf)
    elif cmd == "encrypt-file" and len(sys.argv) >= 4:
        src, out = Path(sys.argv[2]), Path(sys.argv[3])
        sign = "--sign" in sys.argv
        pp = os.environ.get("ENCRYPT_PASSPHRASE", "").strip()
        if not pp:
            pp = getpass.getpass("Passphrase: ")
        it = conf["PBKDF2_ITERATIONS"]
        persist = conf.get("PASSPHRASE_PERSIST", "session")
        if src.suffix.lower() in HTML_EXTENSIONS:
            encrypt_html_file(src, out / src.name, pp, it, persist, sign)
        else:
            encrypt_binary_file(src, out / (src.name + ".enc"),
                                out / (src.name + ".enc.sig"), pp, it, sign)
        print(f"  Done: {src.name}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
