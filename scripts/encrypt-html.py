#!/usr/bin/env python3
"""
encrypt-html.py — Encrypt files using AES-256-GCM + PBKDF2-SHA256

Modes:
  encrypt-html.py <domain>                Domain mode (e.g. dpcpbp.org)
  encrypt-html.py <file> <output_dir>     Encrypt a single file
  encrypt-html.py --test                  Round-trip test

Domain mode:
  Source:  /var/www/utils/<domain>/{html,pdf,docx,txt,...}
  Output:  /var/www/htdocs/<domain>/files/{html,pdf,docx,txt,...}

  HTML files   → encrypted .html with embedded JS decryptor + embedded GPG sig
  Other files  → encrypted .enc (JSON) + detached .sig

  Passphrase read from /var/www/utils/<domain>/passphrase.txt
"""

import sys
import os
import json
import base64
import getpass
import argparse
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from html.parser import HTMLParser

ITERATIONS = 260_000
SALT_LEN   = 32
IV_LEN     = 12

UTILS_BASE  = Path("/var/www/utils")
HTDOCS_BASE = Path("/var/www/htdocs")

HTML_EXTENSIONS = {".html", ".htm"}

# ── Key derivation ─────────────────────────────────────────────────────────────

def derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))

# ── Encrypt / Decrypt ──────────────────────────────────────────────────────────

def encrypt(plaintext: bytes, passphrase: str) -> dict:
    salt = os.urandom(SALT_LEN)
    iv   = os.urandom(IV_LEN)
    key  = derive_key(passphrase, salt)
    ct   = AESGCM(key).encrypt(iv, plaintext, None)
    return {
        "salt": base64.urlsafe_b64encode(salt).decode(),
        "iv":   base64.urlsafe_b64encode(iv).decode(),
        "ct":   base64.urlsafe_b64encode(ct).decode(),
        "iter": ITERATIONS,
    }

def decrypt(enc: dict, passphrase: str) -> bytes:
    salt = base64.urlsafe_b64decode(enc["salt"])
    iv   = base64.urlsafe_b64decode(enc["iv"])
    ct   = base64.urlsafe_b64decode(enc["ct"])
    key  = derive_key(passphrase, salt)
    return AESGCM(key).decrypt(iv, ct, None)

# ── HTML helpers ───────────────────────────────────────────────────────────────

class TitleExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = ""
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
    def handle_data(self, data):
        if self._in_title:
            self.title += data

def extract_title(html: str) -> str:
    p = TitleExtractor()
    p.feed(html)
    return p.title.strip() or "Encrypted Document"

# ── GPG signing ────────────────────────────────────────────────────────────────

def gpg_sign_data(data: bytes) -> str | None:
    result = subprocess.run(
        ["gpg", "--batch", "--yes", "--detach-sign", "--armor"],
        input=data, capture_output=True
    )
    if result.returncode != 0:
        print(f"  GPG sign failed: {result.stderr.decode().strip()}", file=sys.stderr)
        return None
    return result.stdout.decode()

# ── HTML wrapper with embedded JS decryptor ────────────────────────────────────

def wrap_html_encrypted(enc: dict, title: str, source_filename: str, sig_armor: str = None) -> str:
    enc_json = json.dumps(enc)
    if sig_armor:
        sig_block = (
            '<details class="sig">\n'
            '  <summary>GPG Signature</summary>\n'
            '  <pre class="armor">' + sig_armor.strip() + '</pre>\n'
            '  <p class="hint">verify: <code>verify-html.sh ' + source_filename + '</code></p>\n'
            '</details>'
        )
        sig_style = """
    details.sig { margin-top: 2rem; border-top: 1px solid #222; padding-top: 1rem; text-align: left; }
    details.sig summary { color: #555; cursor: pointer; font-size: 0.8rem; user-select: none; }
    details.sig pre.armor { font-size: 0.65rem; color: #444; white-space: pre-wrap; word-break: break-all; margin: 0.6rem 0 0.4rem; }
    details.sig .hint { font-size: 0.75rem; color: #555; margin: 0; }
    details.sig .hint code { background: #1a1a1a; padding: 1px 4px; border-radius: 3px; }"""
    else:
        sig_block = ""
        sig_style = ""
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
    .spin {{ display: none; margin-top: 0.8rem; color: #666; font-size: 0.85rem; }}{sig_style}
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
{sig_block}
</div>
<pre id="enc-data" style="display:none" aria-hidden="true">{enc_json}</pre>
<script>
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
    let html = new TextDecoder().decode(plain);
    const base = location.origin + location.pathname.replace(/[^/]*$/, '');
    html = html.replace(/<head([^>]*)>/i, '<head$1><base href="' + base + '">');
    const blob = new Blob([html], {{type: 'text/html'}});
    location.href = URL.createObjectURL(blob);
  }} catch (_) {{
    spin.style.display = 'none';
    btn.disabled = false;
    err.textContent = 'Wrong passphrase or corrupted data.';
    document.getElementById('pw').select();
  }}
}}
</script>
</body>
</html>
"""

# ── Encrypt operations ─────────────────────────────────────────────────────────

def needs_update(src: Path, dest: Path) -> bool:
    return not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime


def encrypt_html_file(src: Path, dest: Path, passphrase: str) -> bool:
    """Encrypt an HTML file with embedded JS decryptor + embedded GPG sig.
    Returns True if file was updated."""
    if not needs_update(src, dest):
        return False
    data = src.read_bytes()
    title = extract_title(data.decode("utf-8", errors="replace"))
    enc = encrypt(data, passphrase)
    enc_json = json.dumps(enc)
    sig_armor = gpg_sign_data(enc_json.encode())
    wrapped = wrap_html_encrypted(enc, title, src.name, sig_armor)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(wrapped)
    return True


def encrypt_binary_file(src: Path, dest_enc: Path, dest_sig: Path, passphrase: str) -> bool:
    """Encrypt a non-HTML file to .enc (JSON) + detached .sig.
    Returns True if file was updated."""
    if not needs_update(src, dest_enc):
        return False
    data = src.read_bytes()
    enc = encrypt(data, passphrase)
    enc["filename"] = src.name
    enc_json = json.dumps(enc, indent=2)
    dest_enc.parent.mkdir(parents=True, exist_ok=True)
    dest_enc.write_text(enc_json)
    sig_armor = gpg_sign_data(enc_json.encode())
    if sig_armor:
        dest_sig.write_text(sig_armor)
    return True


def encrypt_domain(domain: str):
    """
    Domain mode — encrypt everything in utils/<domain>/ to htdocs/<domain>/files/.

    Source structure (in /var/www/utils/<domain>/):
      html/       → HTML files
      pdf/        → PDFs
      docx/       → Word docs
      txt/        → text files
      ...any other subdirs...

    Output structure (in /var/www/htdocs/<domain>/):
      files/html/*.html       → encrypted HTML with embedded JS decryptor
      files/pdf/*.pdf.enc     → encrypted binary + .sig
      files/docx/*.docx.enc   → encrypted binary + .sig
      files/txt/*.txt.enc     → encrypted binary + .sig
      ...mirrors source structure...
    """
    utils_dir  = UTILS_BASE / domain
    htdocs_dir = HTDOCS_BASE / domain
    files_dir  = htdocs_dir / "files"

    pp_file = utils_dir / "passphrase.txt"
    if not pp_file.exists() or not pp_file.stat().st_size:
        print(f"Error: passphrase not found: {pp_file}", file=sys.stderr)
        sys.exit(1)
    passphrase = pp_file.read_text().strip()

    files_dir.mkdir(parents=True, exist_ok=True)

    # Collect all source files from utils subdirectories
    # Skip: passphrase.txt, *.sh, *.py, keys/, add/, and any dotfiles
    skip_names = {"passphrase.txt", "add", "keys", "Documents", "Old", "__pycache__", "downloads"}
    skip_exts  = {".sh", ".py", ".tgz", ".asc", ".sig"}

    html_count = 0
    bin_count  = 0
    html_updated = 0
    bin_updated  = 0

    for subdir in sorted(utils_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if subdir.name in skip_names or subdir.name.startswith("."):
            continue

        for src in sorted(subdir.rglob("*")):
            if not src.is_file():
                continue
            if src.suffix.lower() in skip_exts:
                continue

            # Relative path from utils_dir preserving structure
            rel = src.relative_to(utils_dir)
            dest_subdir = files_dir / rel.parent
            dest_subdir.mkdir(parents=True, exist_ok=True)

            if src.suffix.lower() in HTML_EXTENSIONS:
                html_count += 1
                dest = dest_subdir / src.name
                if encrypt_html_file(src, dest, passphrase):
                    html_updated += 1
                    print(f"  [html] {rel}")
                else:
                    print(f"  [skip] {rel}")
            else:
                bin_count += 1
                dest_enc = dest_subdir / (src.name + ".enc")
                dest_sig = dest_subdir / (src.name + ".enc.sig")
                if encrypt_binary_file(src, dest_enc, dest_sig, passphrase):
                    bin_updated += 1
                    print(f"  [enc]  {rel}")
                else:
                    print(f"  [skip] {rel}")

    total = html_count + bin_count
    updated = html_updated + bin_updated
    print(f"\n  HTML:  {html_updated}/{html_count} updated")
    print(f"  Other: {bin_updated}/{bin_count} updated")
    print(f"  Total: {updated}/{total}")


# ── Single-file mode ───────────────────────────────────────────────────────────

def encrypt_single(src_path: str, dest_dir: str, sign: bool):
    src = Path(src_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    passphrase = os.environ.get("ENCRYPT_PASSPHRASE", "").strip()
    if not passphrase:
        passphrase = getpass.getpass("Passphrase: ")
        confirm    = getpass.getpass("Confirm:    ")
        if passphrase != confirm:
            print("Passphrases do not match.", file=sys.stderr)
            sys.exit(1)

    if src.suffix.lower() in HTML_EXTENSIONS:
        data = src.read_bytes()
        title = extract_title(data.decode("utf-8", errors="replace"))
        enc = encrypt(data, passphrase)
        enc_json = json.dumps(enc)
        sig_armor = gpg_sign_data(enc_json.encode()) if sign else None
        wrapped = wrap_html_encrypted(enc, title, src.name, sig_armor)
        out = dest / src.name
        out.write_text(wrapped)
        print(f"  encrypted: {out}")
    else:
        enc = encrypt(src.read_bytes(), passphrase)
        enc["filename"] = src.name
        enc_json = json.dumps(enc, indent=2)
        out_enc = dest / (src.name + ".enc")
        out_enc.write_text(enc_json)
        print(f"  encrypted: {out_enc}")
        if sign:
            sig_armor = gpg_sign_data(enc_json.encode())
            if sig_armor:
                out_sig = dest / (src.name + ".enc.sig")
                out_sig.write_text(sig_armor)
                print(f"  signed:    {out_sig}")


# ── Test ───────────────────────────────────────────────────────────────────────

def run_test():
    print("=== Round-trip test ===")
    sample = Path("/tmp/enc-test-sample.html")
    sample.write_text("""<!DOCTYPE html>
<html><head><title>Test Document</title></head>
<body><h1>Hello World</h1><p>Secret content: 42 is the answer.</p></body>
</html>""")

    passphrase = "correct horse battery staple test words here now"
    print(f"Passphrase: {passphrase}")

    # Test HTML encryption
    enc = encrypt(sample.read_bytes(), passphrase)
    recovered = decrypt(enc, passphrase).decode("utf-8")
    assert "Secret content: 42" in recovered, "HTML round-trip failed!"
    print("  HTML round-trip: OK")

    # Test binary encryption
    bindata = b"\x00\x01\x02\xff" * 100
    enc2 = encrypt(bindata, passphrase)
    recovered2 = decrypt(enc2, passphrase)
    assert recovered2 == bindata, "Binary round-trip failed!"
    print("  Binary round-trip: OK")

    print("=== Test passed ===")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input",  nargs="?", help="Domain name, file, or directory")
    parser.add_argument("output", nargs="?", help="Output directory (single-file mode)")
    parser.add_argument("--test", action="store_true", help="Run round-trip test")
    parser.add_argument("--sign", action="store_true", help="GPG-sign (single-file mode)")
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    # Domain shortcut: single arg with a dot and no path separators
    if args.output is None and "." in args.input and "/" not in args.input:
        encrypt_domain(args.input)
        return

    if not args.output:
        parser.print_help()
        sys.exit(1)

    encrypt_single(args.input, args.output, args.sign)

if __name__ == "__main__":
    main()
