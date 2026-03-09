#!/usr/bin/env python3
"""
decrypt.py — Offline decryption for .enc files and encrypted HTML

Decrypts files encrypted by encrypt-html.py.

Usage:
  decrypt.py <file.enc>              Decrypt a .enc file (prompts for passphrase)
  decrypt.py <file.enc> -o out.pdf   Decrypt to specific output file
  decrypt.py <file.html>             Extract and decrypt an encrypted HTML page
  decrypt.py --verify <file.enc>     Verify GPG signature (.enc.sig must exist)

The .enc format is JSON: {"salt", "iv", "ct", "iter", "filename"}
Encrypted HTML files have the payload in a <pre id="enc-data"> tag.

Dependencies: python3, cryptography (pip install cryptography)
              gpg (only for --verify)
"""

import sys
import os
import json
import re
import base64
import getpass
import argparse
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def decrypt_payload(enc: dict, passphrase: str) -> bytes:
    salt = base64.urlsafe_b64decode(enc["salt"])
    iv   = base64.urlsafe_b64decode(enc["iv"])
    ct   = base64.urlsafe_b64decode(enc["ct"])
    iterations = int(enc.get("iter", 260000))
    key = derive_key(passphrase, salt, iterations)
    return AESGCM(key).decrypt(iv, ct, None)


def load_enc_file(path: Path) -> dict:
    """Load a .enc JSON file."""
    return json.loads(path.read_text())


def load_enc_html(path: Path) -> dict:
    """Extract encrypted payload from an HTML file."""
    html = path.read_text(errors="replace")
    m = re.search(r'<pre id="enc-data"[^>]*>(.*?)</pre>', html, re.S)
    if not m:
        print(f"Error: no encrypted payload found in {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(m.group(1).strip())


def verify_sig(enc_path: Path):
    """Verify detached GPG signature."""
    sig_path = Path(str(enc_path) + ".sig")
    if not sig_path.exists():
        print(f"No signature file: {sig_path}", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(
        ["gpg", "--verify", str(sig_path), str(enc_path)],
        capture_output=True, text=True
    )
    print(result.stderr)
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="Encrypted file (.enc or .html)")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("--verify", action="store_true", help="Verify GPG signature")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    if args.verify:
        verify_sig(path)
        return

    # Load encrypted payload
    if path.suffix == ".enc":
        enc = load_enc_file(path)
    elif path.suffix in (".html", ".htm"):
        enc = load_enc_html(path)
    else:
        # Try JSON first, fall back to HTML extraction
        try:
            enc = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            enc = load_enc_html(path)

    # Determine output filename
    if args.output:
        out_path = Path(args.output)
    elif "filename" in enc:
        out_path = Path(enc["filename"])
    elif path.suffix == ".enc":
        out_path = Path(path.stem)  # strip .enc
    else:
        out_path = Path(path.stem + ".decrypted")

    if out_path.exists():
        print(f"Output file already exists: {out_path}", file=sys.stderr)
        print("Use -o to specify a different output path.", file=sys.stderr)
        sys.exit(1)

    passphrase = os.environ.get("ENCRYPT_PASSPHRASE", "").strip()
    if not passphrase:
        passphrase = getpass.getpass("Passphrase: ")

    try:
        plaintext = decrypt_payload(enc, passphrase)
    except Exception:
        print("Decryption failed — wrong passphrase or corrupted data.", file=sys.stderr)
        sys.exit(1)

    out_path.write_bytes(plaintext)
    print(f"Decrypted: {out_path} ({len(plaintext)} bytes)")


if __name__ == "__main__":
    main()
