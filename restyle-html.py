#!/usr/bin/env python3
"""Restyle chat HTML exports: dark mode, anonymize branding, neutral voice labels."""

import os
import re
import sys

DARK_CSS = """    *, *::before, *::after { box-sizing: border-box; }
    :root {
      --bg: #111; --fg: #ccc; --bg2: #1a1a1a; --fg2: #888;
      --v1-bg: #161a16; --v1-border: #4a7; --v2-bg: #161618; --v2-border: #668;
      --code-bg: #0d0d0d; --inline-code-bg: #222; --inline-code-fg: #e06c75;
      --link: #7aa2c8; --border: #222; --table-border: #333; --th-bg: #1a1a1a;
      --shadow: rgba(0,0,0,.3);
    }
    [data-theme="light"] {
      --bg: #f5f5f7; --fg: #1a1a1a; --bg2: #fff; --fg2: #555;
      --v1-bg: #f0f4f0; --v1-border: #5a5; --v2-bg: #f0f0f6; --v2-border: #88a;
      --code-bg: #f6f8fa; --inline-code-bg: #f0f0f0; --inline-code-fg: #c7254e;
      --link: #2563eb; --border: #ddd; --table-border: #ccc; --th-bg: #eee;
      --shadow: rgba(0,0,0,.08);
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      line-height: 1.75; max-width: 900px;
      margin: 0 auto; padding: 2rem 1.5rem 4rem;
      background: var(--bg); color: var(--fg);
      transition: background .2s, color .2s;
    }
    h1 { font-size: 1.5rem; border-bottom: 2px solid var(--border); padding-bottom: .5rem; }
    .meta { font-size: .78rem; color: var(--fg2); margin-bottom: 2rem; }
    .meta a { color: var(--link); }
    .message { margin: 1.25rem 0; padding: 1rem 1.4rem; border-radius: 12px; }
    .msg-user {
      background: var(--v1-bg); border-left: 3px solid var(--v1-border);
    }
    .msg-assistant {
      background: var(--v2-bg); border-left: 3px solid var(--v2-border);
    }
    .voice-tag {
      font-size: .7rem; letter-spacing: .08em;
      color: var(--fg2); margin-bottom: .4rem; opacity: .5;
    }
    .content p { margin: .5rem 0; }
    .content a { color: var(--link); }
    .content pre {
      background: var(--code-bg); border-radius: 8px; overflow-x: auto;
      padding: 1rem; font-size: .875rem; margin: .75rem 0;
    }
    .content code:not(pre code) {
      background: var(--inline-code-bg); padding: 2px 5px;
      border-radius: 4px; font-size: .9em; color: var(--inline-code-fg);
    }
    .content table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }
    .content th, .content td { border: 1px solid var(--table-border); padding: .4rem .7rem; }
    .content th { background: var(--th-bg); font-weight: 600; }
    .content blockquote {
      border-left: 3px solid var(--fg2); margin: .5rem 0; padding-left: 1rem; color: var(--fg2);
    }
    .content img { max-width: 100%; border-radius: 6px; }
    .content ol, .content ul { padding-left: 1.5rem; }
    .content h1,.content h2,.content h3 { margin-top: 1.1rem; }
    .table-wrap { overflow-x: auto; margin: 1rem 0; }
    mjx-container { overflow-x: auto; }
    .theme-toggle {
      position: fixed; top: 1rem; right: 1rem;
      background: var(--bg2); border: 1px solid var(--border);
      border-radius: 6px; padding: 0.3rem 0.6rem;
      color: var(--fg); cursor: pointer; font-size: 1rem;
      z-index: 1000; opacity: 0.7; transition: opacity .2s;
    }
    .theme-toggle:hover { opacity: 1; }"""

THEME_TOGGLE_HTML = '<button class="theme-toggle" onclick="let t=document.documentElement;t.dataset.theme=t.dataset.theme===\'light\'?\'dark\':\'light\'" title="Toggle light/dark mode">\u263c</button>'

# Full <style>...</style> block
STYLE_BLOCK = re.compile(r'<style>\s*.*?</style>', re.DOTALL)

# Role label div: any combo of emoji (entity/literal) + name + optional turn span
# Replace entire div with neutral voice tag
ROLE_LABEL_USER = re.compile(
    r'<div class="role-label">[^<]*(?:<[^>]*>[^<]*)*</div>\s*(?=<div class="content">)',
)

# "Exported from <AI>" in meta
EXPORTED_PATTERN = re.compile(r'Exported from (Claude|Gemini|ChatGPT|DeepSeek)', re.IGNORECASE)

# <title>Google</title>
GOOGLE_TITLE = re.compile(r'<title>Google</title>')
WOLFRAM_TITLE = re.compile(r'<title>Wolfram - ([^<]+)</title>')


def assign_voices(html):
    """Replace role-label divs with voice tags, tracking voice number by class."""
    def replace_label(m):
        # Determine voice from surrounding message div
        # Look backward to find msg-user or msg-assistant
        start = m.start()
        chunk = html[max(0, start - 200):start]
        if 'msg-user' in chunk:
            return '<div class="voice-tag">&#x25B8;</div>\n'
        else:
            return '<div class="voice-tag">&#x25BE;</div>\n'
    return ROLE_LABEL_USER.sub(replace_label, html)


def restyle(html):
    # Replace <title>Google</title>
    html = GOOGLE_TITLE.sub('<title>Conversation</title>', html)
    # Strip "Wolfram - " prefix from titles
    html = WOLFRAM_TITLE.sub(r'<title>\1</title>', html)
    # Replace <h1>Google</h1>
    html = re.sub(r'<h1>Google</h1>', '<h1>Conversation</h1>', html)
    # Strip "Wolfram - " from h1
    html = re.sub(r'<h1>Wolfram - ', '<h1>', html)

    # Replace style block
    html = STYLE_BLOCK.sub(f'<style>\n{DARK_CSS}\n  </style>', html, count=1)

    # Replace role labels with minimal voice indicators
    html = assign_voices(html)

    # Anonymize export source
    html = EXPORTED_PATTERN.sub('Exported', html)

    # Inject theme toggle after <body>
    html = html.replace('<body>', f'<body>\n  {THEME_TOGGLE_HTML}', 1)

    return html


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_dir>", file=sys.stderr)
        print(f"       {sys.argv[0]} <file.html>  (preview to stdout)", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            print(restyle(f.read()))
        return

    indir, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    count = 0
    for name in sorted(os.listdir(indir)):
        if not name.endswith('.html'):
            continue
        with open(os.path.join(indir, name)) as f:
            html = f.read()
        with open(os.path.join(outdir, name), 'w') as f:
            f.write(restyle(html))
        count += 1

    print(f"Restyled {count} files \u2192 {outdir}")


if __name__ == '__main__':
    main()
