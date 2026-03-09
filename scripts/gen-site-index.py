#!/usr/bin/env python3
"""
gen-site-index.py — Generate encrypted index.html for a domain.

Scans /var/www/htdocs/<domain>/files/html/ for encrypted HTML files,
builds an index page with links to each, encrypts and signs it, and
writes it to /var/www/htdocs/<domain>/index.html.

The index page is itself encrypted with the same passphrase and has
an embedded JS decryptor.

Usage:
  gen-site-index.py <domain>       e.g. gen-site-index.py dpcpbp.org
"""

import sys
import os
import re
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

# Reuse crypto from encrypt-html.py
from importlib.machinery import SourceFileLoader
_enc = SourceFileLoader("enc", str(Path(__file__).parent / "encrypt-html.py")).load_module()

UTILS_BASE  = Path("/var/www/utils")
HTDOCS_BASE = Path("/var/www/htdocs")


def extract_encrypted_title(html: str, fallback: str) -> str:
    """Extract original title from an already-encrypted HTML file."""
    m = re.search(r'<title>(.*?)\s*\[encrypted\]</title>', html, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r'<title>(.*?)</title>', html, re.I)
    return m.group(1).strip() if m else fallback


def build_index_html(domain: str, items: list[tuple[str, str, str]]) -> str:
    """Build plaintext index page. items: [(filename, title, href), ...]"""
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    links = "\n".join(
        f'<li><a href="{href}">{title}</a></li>'
        for _, title, href in items
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{domain}</title>
  <style>
    body {{ font-family: sans-serif; background: #111; color: #ccc;
           max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
    .header {{ display: flex; justify-content: space-between; align-items: baseline;
               border-bottom: 1px solid #222; padding-bottom: 0.8rem; margin-bottom: 1.2rem; }}
    h1 {{ font-size: 1rem; color: #888; font-weight: normal; margin: 0; }}
    a.files-link {{ font-size: 0.85rem; color: #7aa2c8; text-decoration: none; }}
    a.files-link:hover {{ text-decoration: underline; }}
    ul {{ list-style: none; padding: 0; margin: 0; column-count: 2; column-gap: 2rem; }}
    li {{ padding: 0.15rem 0; font-size: 0.85rem; break-inside: avoid; }}
    li a {{ color: #aaa; text-decoration: none; }}
    li a:hover {{ color: #ddd; }}
    .footer {{ margin-top: 2rem; font-size: 0.75rem; color: #333;
               border-top: 1px solid #1a1a1a; padding-top: 0.8rem; }}
  </style>
</head>
<body>
<div class="header">
  <h1>{domain} &mdash; {len(items)} documents</h1>
  <a class="files-link" href="files/">Files &amp; Downloads &rarr;</a>
</div>
<ul>
{links}
</ul>
<p class="footer">Generated {generated} &middot; All documents encrypted &middot; <a href="files/pubkey.asc" style="color:#333">pubkey.asc</a></p>
</body>
</html>
"""


def human_size(size: int) -> str:
    """Format byte size as human-readable."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def build_files_index_html(domain: str, files_dir: Path) -> str:
    """Build plaintext directory listing for /files/. Groups by subdirectory."""
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Collect all files grouped by subdirectory
    sections = {}
    for p in sorted(files_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(files_dir)
        # Skip the index.html we're about to create
        if str(rel) == "index.html":
            continue
        parts = rel.parts
        # Skip junk/duplicate directories
        skip_dirs = {"Documents", "Old", "__pycache__", "downloads"}
        if parts[0] in skip_dirs:
            continue
        section = parts[0] if len(parts) > 1 else "."
        if section not in sections:
            sections[section] = []
        sections[section].append((str(rel), p.name, p.stat().st_size))

    total_files = sum(len(v) for v in sections.values())

    # Build HTML sections
    section_html = []
    for section_name in sorted(sections.keys()):
        files = sections[section_name]
        label = section_name if section_name != "." else "root"
        rows = "\n".join(
            f'    <tr><td><a href="{rel}">{name}</a></td>'
            f'<td class="size">{human_size(size)}</td></tr>'
            for rel, name, size in sorted(files, key=lambda x: x[1].lower())
        )
        section_html.append(
            f'<h2>{label}/ <span class="count">({len(files)})</span></h2>\n'
            f'<table>\n{rows}\n</table>'
        )

    body = "\n".join(section_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{domain} — files</title>
  <style>
    body {{ font-family: sans-serif; background: #111; color: #ccc;
           max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
    h1 {{ font-size: 1rem; color: #888; font-weight: normal;
         border-bottom: 1px solid #222; padding-bottom: 0.8rem; }}
    h1 a {{ color: #7aa2c8; text-decoration: none; font-size: 0.85rem; margin-left: 1rem; }}
    h1 a:hover {{ text-decoration: underline; }}
    h2 {{ font-size: 0.9rem; color: #777; margin: 1.5rem 0 0.5rem; }}
    h2 .count {{ color: #555; font-weight: normal; }}
    table {{ width: 100%; border-collapse: collapse; }}
    tr:hover {{ background: #1a1a1a; }}
    td {{ padding: 0.2rem 0.4rem; font-size: 0.82rem; }}
    td a {{ color: #aaa; text-decoration: none; }}
    td a:hover {{ color: #ddd; }}
    td.size {{ color: #555; text-align: right; white-space: nowrap; width: 5rem; }}
    .footer {{ margin-top: 2rem; font-size: 0.75rem; color: #333;
               border-top: 1px solid #1a1a1a; padding-top: 0.8rem; }}
  </style>
</head>
<body>
<h1>{domain} — {total_files} files <a href="/">&larr; Index</a></h1>
{body}
<p class="footer">Generated {generated} &middot; <a href="pubkey.asc" style="color:#333">pubkey.asc</a></p>
</body>
</html>
"""


def extract_gpg_sig(html: str) -> str:
    """Extract the GPG signature armor from an encrypted HTML file."""
    m = re.search(r'(-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----)', html, re.S)
    return m.group(1).strip() if m else ""


def get_gpg_fingerprint() -> str:
    """Get the GPG key fingerprint used for signing."""
    try:
        r = subprocess.run(["gpg", "--list-keys", "--with-colons"],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith("fpr:"):
                return line.split(":")[9]
    except Exception:
        pass
    return "unknown"


def build_manifest_txt(domain: str, items: list, files_dir: Path, fingerprint: str) -> str:
    """Build plaintext manifest for web archivers. Lists every document with
    title, filename, SHA-256 of encrypted file, and GPG signature."""
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = []
    lines.append(f"MANIFEST — {domain}")
    lines.append(f"Generated: {generated}")
    lines.append(f"GPG Key Fingerprint: {fingerprint}")
    lines.append(f"Public Key: https://{domain}/files/pubkey.asc")
    lines.append(f"Documents: {len(items)}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("")

    for filename, title, href in items:
        enc_path = files_dir / "html" / filename
        sha256 = ""
        sig = ""
        if enc_path.exists():
            sha256 = hashlib.sha256(enc_path.read_bytes()).hexdigest()
            sig = extract_gpg_sig(enc_path.read_text(errors="replace"))
        lines.append(f"Title:    {title}")
        lines.append(f"File:     {filename}")
        lines.append(f"URL:      https://{domain}/{href}")
        lines.append(f"SHA-256:  {sha256}")
        if sig:
            lines.append(f"GPG Sig:  {sig}")
        lines.append("")

    # Also list non-HTML files
    skip_dirs = {"Documents", "Old", "__pycache__", "downloads"}
    for subdir in sorted(files_dir.iterdir()):
        if not subdir.is_dir() or subdir.name in skip_dirs or subdir.name == "html":
            continue
        for f in sorted(subdir.iterdir()):
            if not f.is_file():
                continue
            sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
            rel = f.relative_to(files_dir)
            lines.append(f"File:     {f.name}")
            lines.append(f"URL:      https://{domain}/files/{rel}")
            lines.append(f"SHA-256:  {sha256}")
            lines.append("")

    return "\n".join(lines)


def build_manifest_html(domain: str, items: list, files_dir: Path, fingerprint: str) -> str:
    """Build HTML manifest page — plaintext, unencrypted, archiver-friendly."""
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = []
    for filename, title, href in items:
        enc_path = files_dir / "html" / filename
        sha256 = ""
        if enc_path.exists():
            sha256 = hashlib.sha256(enc_path.read_bytes()).hexdigest()
        rows.append(
            f'<tr><td class="t">{title}</td>'
            f'<td><a href="{href}">{filename}</a></td>'
            f'<td class="h">{sha256[:16]}...</td></tr>'
        )

    table = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{domain} — Document Manifest</title>
  <style>
    body {{ font-family: monospace; background: #111; color: #ccc;
           max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
    h1 {{ font-size: 1rem; color: #888; font-weight: normal;
         border-bottom: 1px solid #222; padding-bottom: 0.8rem; }}
    .meta {{ font-size: 0.8rem; color: #555; margin-bottom: 1.5rem; }}
    .meta a {{ color: #7aa2c8; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; }}
    th {{ text-align: left; color: #555; border-bottom: 1px solid #222;
         padding: 0.3rem 0.4rem; font-weight: normal; }}
    td {{ padding: 0.2rem 0.4rem; border-bottom: 1px solid #1a1a1a; }}
    td.t {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    td.h {{ color: #555; font-size: 0.7rem; }}
    td a {{ color: #aaa; text-decoration: none; }}
    td a:hover {{ color: #ddd; }}
    .footer {{ margin-top: 2rem; font-size: 0.7rem; color: #333;
               border-top: 1px solid #1a1a1a; padding-top: 0.8rem; }}
  </style>
</head>
<body>
<h1>{domain} — Document Manifest ({len(items)} documents)</h1>
<div class="meta">
  Generated: {generated}<br>
  GPG Fingerprint: <code>{fingerprint}</code><br>
  Public Key: <a href="files/pubkey.asc">pubkey.asc</a> |
  Full manifest: <a href="manifest.txt">manifest.txt</a>
</div>
<table>
<tr><th>Title</th><th>File</th><th>SHA-256</th></tr>
{table}
</table>
<p class="footer">All documents are AES-256-GCM encrypted. GPG signatures embedded in each file.
Verify with pubkey.asc. Full manifest with signatures: <a href="manifest.txt" style="color:#555">manifest.txt</a></p>
</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    domain = sys.argv[1]
    utils_dir  = UTILS_BASE / domain
    htdocs_dir = HTDOCS_BASE / domain
    files_dir  = htdocs_dir / "files"
    files_html = files_dir / "html"

    pp_file = utils_dir / "passphrase.txt"
    if not pp_file.exists() or not pp_file.stat().st_size:
        print(f"Error: passphrase not found: {pp_file}", file=sys.stderr)
        sys.exit(1)
    passphrase = pp_file.read_text().strip()

    if not files_html.is_dir():
        print(f"No files/html/ directory: {files_html}", file=sys.stderr)
        sys.exit(1)

    # ── Main index (root index.html) ──────────────────────────────────────
    items = []
    for f in sorted(files_html.iterdir()):
        if f.is_file() and f.suffix.lower() in (".html", ".htm"):
            title = extract_encrypted_title(f.read_text(errors="replace"), f.stem)
            items.append((f.name, title, f"files/html/{f.name}"))

    print(f"  Building index: {len(items)} documents")

    plaintext = build_index_html(domain, items)
    enc = _enc.encrypt(plaintext.encode("utf-8"), passphrase)
    enc_json = json.dumps(enc)
    sig_armor = _enc.gpg_sign_data(enc_json.encode())
    wrapped = _enc.wrap_html_encrypted(enc, domain, "index.html", sig_armor)

    dest = htdocs_dir / "index.html"
    dest.write_text(wrapped)
    print(f"  index.html → {dest} ({len(items)} documents)")

    # ── Files directory index (files/index.html) ──────────────────────────
    print(f"  Building files index...")
    files_plaintext = build_files_index_html(domain, files_dir)
    files_enc = _enc.encrypt(files_plaintext.encode("utf-8"), passphrase)
    files_enc_json = json.dumps(files_enc)
    files_sig = _enc.gpg_sign_data(files_enc_json.encode())
    files_wrapped = _enc.wrap_html_encrypted(
        files_enc, f"{domain} — files", "files/index.html", files_sig
    )

    files_dest = files_dir / "index.html"
    files_dest.write_text(files_wrapped)
    print(f"  files/index.html → {files_dest}")

    # ── Manifests (plaintext, unencrypted — for web archivers) ────────────
    print(f"  Building manifests...")
    fingerprint = get_gpg_fingerprint()

    manifest_txt = build_manifest_txt(domain, items, files_dir, fingerprint)
    txt_dest = htdocs_dir / "manifest.txt"
    txt_dest.write_text(manifest_txt)
    print(f"  manifest.txt → {txt_dest}")

    manifest_html = build_manifest_html(domain, items, files_dir, fingerprint)
    html_dest = htdocs_dir / "manifest.html"
    html_dest.write_text(manifest_html)
    print(f"  manifest.html → {html_dest}")


if __name__ == "__main__":
    main()
