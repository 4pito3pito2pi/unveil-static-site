#!/usr/bin/env python3
"""decrypt.py — offline decryption for locksite files

Usage:
  decrypt.py <file.html>           Decrypt HTML, write to stdout
  decrypt.py <file.enc> -o <out>   Decrypt binary, write to file
"""
import sys, os, json, re, base64, getpass
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def decrypt(enc, passphrase):
    salt = base64.urlsafe_b64decode(enc["salt"])
    iv   = base64.urlsafe_b64decode(enc["iv"])
    ct   = base64.urlsafe_b64decode(enc["ct"])
    kdf  = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                      salt=salt, iterations=int(enc.get("iter", 260000)))
    key = kdf.derive(passphrase.encode())
    return AESGCM(key).decrypt(iv, ct, None)

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    data = open(src).read()
    # Extract JSON payload from HTML or raw .enc
    m = re.search(r'\{[^{}]*"salt"[^{}]*"ct"[^{}]*\}', data)
    if not m:
        print("No encrypted payload found", file=sys.stderr); sys.exit(1)
    enc = json.loads(m.group())
    pp = os.environ.get("ENCRYPT_PASSPHRASE") or getpass.getpass("Passphrase: ")
    plain = decrypt(enc, pp.strip())
    if "-o" in sys.argv:
        out = sys.argv[sys.argv.index("-o") + 1]
        open(out, "wb").write(plain)
        print(f"Decrypted: {out}")
    else:
        sys.stdout.buffer.write(plain)

if __name__ == "__main__":
    main()
