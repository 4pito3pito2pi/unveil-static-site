#!/usr/bin/env python3
"""
gen-files-index.py — generate /files/index.html listing all downloadable files

Usage:
  gen-files-index.py <domain>      e.g. gen-files-index.py dpcpbp.org
  gen-files-index.py <directory>   e.g. gen-files-index.py /var/www/htdocs/dpcpbp.org/files
"""

import sys
import re
from pathlib import Path
from datetime import datetime

HTDOCS_BASE = Path("/var/www/htdocs")

# Extensions to skip (signatures, indexes, hidden files)
SKIP_SUFFIXES = {".sig"}
SKIP_NAMES    = {"index.html"}

def original_name_and_type(filename: str):
    """
    Return (display_name, type_label) for a file in /files/.
    Binary encrypted files are stored as 'paper.pdf.html' — we unwrap that.
    Plain encrypted HTML is stored as 'essay.html'.
    """
    # Binary wrapper: ends in .<ext>.html where <ext> is not htm
    import re as _re
    m = _re.match(r'^(.+\.\w+)\.html$', filename, _re.I)
    if m:
        inner = m.group(1)
        inner_ext = Path(inner).suffix.lower()
        if inner_ext not in (".html", ".htm"):
            label = TYPE_LABEL.get(inner_ext, inner_ext.lstrip(".") or "file")
            return inner, label
    # Regular encrypted HTML
    ext = Path(filename).suffix.lower()
    label = TYPE_LABEL.get(ext, ext.lstrip(".") or "file")
    return filename, label

TYPE_LABEL = {
    ".html": "html",
    ".htm":  "html",
    ".pdf":  "pdf",
    ".tex":  "tex",
    ".py":   "py",
    ".wav":  "wav",
    ".mp3":  "mp3",
    ".flac": "flac",
    ".txt":  "txt",
    ".md":   "md",
    ".json": "json",
    ".csv":  "csv",
    ".zip":  "zip",
    ".tgz":  "tgz",
    ".gz":   "gz",
}

TYPE_COLOR = {
    "html": "#7aa2c8",
    "pdf":  "#c87a7a",
    "tex":  "#a0c87a",
    "py":   "#c8b87a",
    "wav":  "#a07ac8",
    "mp3":  "#a07ac8",
    "flac": "#a07ac8",
    "txt":  "#888",
    "md":   "#888",
}


def extract_title(html: str, fallback: str) -> str:
    m = re.search(r'<title>(.*?)\s*\[encrypted\]</title>', html, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r'<title>(.*?)</title>', html, re.I)
    return m.group(1).strip() if m else fallback


def fmt_size(path: Path) -> str:
    b = path.stat().st_size
    if b < 1024:          return f"{b} B"
    if b < 1024 * 1024:   return f"{b/1024:.0f} KB"
    return f"{b/1024/1024:.1f} MB"


def generate_index(files_dir: Path) -> None:
    all_files = sorted(
        f for f in files_dir.iterdir()
        if f.is_file()
        and f.name not in SKIP_NAMES
        and f.suffix.lower() not in SKIP_SUFFIXES
    )

    if not all_files:
        print(f"No files found in {files_dir}")
        return

    rows = []
    for f in all_files:
        display_name, label = original_name_and_type(f.name)
        color = TYPE_COLOR.get(label, "#666")

        # Title: extract from encrypted HTML wrapper, else use display stem
        title = extract_title(f.read_text(errors="replace"), Path(display_name).stem)

        size     = fmt_size(f)
        sig      = f.parent / (f.name + ".sig")
        sig_cell = (f'<a href="{f.name}.sig" download class="sig">sig</a>'
                    if sig.exists() else "")

        rows.append(
            f'    <tr>\n'
            f'      <td class="type"><span style="color:{color}">{label}</span></td>\n'
            f'      <td class="name"><a href="{f.name}">{display_name}</a></td>\n'
            f'      <td class="title">{title}</td>\n'
            f'      <td class="size">{size}</td>\n'
            f'      <td class="sigcol">{sig_cell}</td>\n'
            f'    </tr>'
        )

    domain    = files_dir.parent.name
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    rows_html = "\n".join(rows)

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{domain} — files</title>
  <style>
    body {{ font-family: monospace; background: #111; color: #999;
           max-width: 960px; margin: 3rem auto; padding: 0 1rem; }}
    h1 {{ color: #ccc; font-size: 1.1rem; margin-bottom: 0.3rem; }}
    p.sub {{ color: #555; font-size: 0.8rem; margin: 0 0 2rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; color: #444; font-size: 0.75rem; font-weight: normal;
          border-bottom: 1px solid #222; padding: 0.3rem 0.6rem; }}
    td {{ padding: 0.35rem 0.6rem; border-bottom: 1px solid #1a1a1a; font-size: 0.82rem; vertical-align: middle; }}
    td.type {{ width: 3.5rem; }}
    td.name a {{ color: #7aa2c8; text-decoration: none; }}
    td.name a:hover {{ text-decoration: underline; }}
    td.title {{ color: #666; }}
    td.size {{ color: #444; text-align: right; white-space: nowrap; }}
    td.sigcol {{ text-align: center; width: 2.5rem; }}
    a.sig {{ color: #5a7a5a; font-size: 0.72rem; text-decoration: none; }}
    a.sig:hover {{ text-decoration: underline; }}
    p.note {{ color: #444; font-size: 0.75rem; margin-top: 2rem; line-height: 1.7; }}
    code {{ background: #1a1a1a; padding: 1px 4px; border-radius: 3px; color: #888; }}
  </style>
</head>
<body>
<h1>{domain} — files</h1>
<p class="sub">Generated {generated} &nbsp;·&nbsp; {len(all_files)} files</p>
<table>
  <thead>
    <tr><th>Type</th><th>File</th><th>Title / Description</th><th>Size</th><th>Sig</th></tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
<p class="note">
  HTML files are AES-256-GCM encrypted. Download and decrypt offline:<br>
  &nbsp;&nbsp;<code>python3 decrypt.py file.html</code>&nbsp; or paste <code>decrypt.js</code> into browser console.<br>
  Verify GPG authorship: <code>gpg --verify file.html.sig file.html</code>
</p>
</body>
</html>
"""

    out = files_dir / "index.html"
    out.write_text(index_html)
    print(f"  Written: {out}  ({len(all_files)} files listed)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]
    files_dir = Path(arg) if "/" in arg else HTDOCS_BASE / arg / "files"

    if not files_dir.is_dir():
        print(f"Directory not found: {files_dir}", file=sys.stderr)
        sys.exit(1)

    generate_index(files_dir)


if __name__ == "__main__":
    main()
