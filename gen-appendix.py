#!/usr/bin/env python3
"""Generate paginated HTML corpus + ternary tree word index appendix.

Reads rawcorpus.txt and lexicalfrequency.txt, produces:
  rawcorpus.html  — corpus with page anchors (A4/12pt simulation)
  appendix.html   — top 81 words as 4-deep ternary tree, links into corpus

Usage: gen-appendix.py <corpus_dir> <output_dir>
"""

import html
import os
import re
import sys

# A4 pagination constants (from Wolfram calculation)
LINES_PER_PAGE = 41
CHARS_PER_LINE = 62  # monospace at 12pt

DARK_CSS = """
:root {
  --bg: #111; --fg: #ccc; --bg2: #1a1a1a; --fg2: #888;
  --border: #222; --link: #7aa2c8; --highlight: #2a2a00;
  --shadow: rgba(0,0,0,.3);
}
[data-theme="light"] {
  --bg: #f5f5f7; --fg: #1a1a1a; --bg2: #fff; --fg2: #555;
  --border: #ddd; --link: #2563eb; --highlight: #ffffcc;
  --shadow: rgba(0,0,0,.08);
}
body {
  font-family: 'Courier New', monospace;
  line-height: 1.4; max-width: 960px;
  margin: 0 auto; padding: 2rem 1.5rem;
  background: var(--bg); color: var(--fg);
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
.theme-toggle {
  position: fixed; top: 1rem; right: 1rem;
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.3rem 0.6rem;
  color: var(--fg); cursor: pointer; font-size: 1rem;
  z-index: 1000; opacity: 0.7;
}
.theme-toggle:hover { opacity: 1; }
"""

TOGGLE_BTN = '<button class="theme-toggle" onclick="let t=document.documentElement;t.dataset.theme=t.dataset.theme===\'light\'?\'dark\':\'light\'">&#x263c;</button>'


def wrap_lines(text_lines, chars_per_line):
    """Wrap corpus lines to simulate fixed-width page layout. Yield (original_line_idx, wrapped_text)."""
    for idx, line in enumerate(text_lines):
        line = line.rstrip('\n')
        if not line:
            yield (idx, '')
            continue
        pos = 0
        while pos < len(line):
            yield (idx, line[pos:pos + chars_per_line])
            pos += chars_per_line
        if pos == 0:
            yield (idx, '')


def paginate_corpus(corpus_path):
    """Read corpus, wrap lines, assign pages. Return (pages, line_to_page)."""
    with open(corpus_path) as f:
        raw_lines = f.readlines()

    wrapped = list(wrap_lines(raw_lines, CHARS_PER_LINE))

    pages = []
    line_to_page = {}  # raw line index -> page number (1-based)
    current_page = []
    page_num = 1

    for raw_idx, text in wrapped:
        if raw_idx not in line_to_page:
            line_to_page[raw_idx] = page_num
        current_page.append(text)
        if len(current_page) >= LINES_PER_PAGE:
            pages.append(current_page)
            current_page = []
            page_num += 1

    if current_page:
        pages.append(current_page)

    return pages, line_to_page, raw_lines


def build_word_index(raw_lines, line_to_page, words):
    """For each word, find all pages where it occurs. Return {word: sorted [page_nums]}."""
    word_set = set(w.lower() for w in words)
    index = {w: set() for w in word_set}
    word_re = {w: re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in word_set}

    for line_idx, line in enumerate(raw_lines):
        page = line_to_page.get(line_idx)
        if page is None:
            continue
        for w in word_set:
            if word_re[w].search(line):
                index[w].add(page)

    return {w: sorted(pages) for w, pages in index.items()}


def ternary_address(n, depth=4):
    """Convert index 0-80 to ternary address of given depth."""
    digits = []
    for _ in range(depth):
        digits.append(n % 3)
        n //= 3
    return list(reversed(digits))


def build_tree(words_with_pages):
    """Build nested ternary tree structure from 81 words."""
    # Tree node: {0: ..., 1: ..., 2: ..., 'leaf': (word, pages)}
    root = {}
    for i, (word, pages) in enumerate(words_with_pages):
        addr = ternary_address(i)
        node = root
        for d in range(len(addr) - 1):
            digit = addr[d]
            if digit not in node:
                node[digit] = {}
            node = node[digit]
        node[addr[-1]] = {'_leaf': (word, pages)}
    return root


def render_tree_html(node, depth=0, path=""):
    """Render tree as nested HTML with <details> for unfolding."""
    parts = []
    for digit in (0, 1, 2):
        if digit not in node:
            continue
        child = node[digit]
        label = f"{path}{digit}"
        if '_leaf' in child:
            word, pages = child['_leaf']
            # Leaf: show word and page links
            # Compress page ranges for display
            page_links = compress_pages(pages)
            parts.append(
                f'<div class="leaf" style="margin-left:{depth*1.5}rem">'
                f'<span class="node-addr">[{label}]</span> '
                f'<strong>{html.escape(word)}</strong> '
                f'<span class="pg-count">({len(pages)} pp.)</span>'
                f'<div class="page-refs">{page_links}</div>'
                f'</div>\n'
            )
        else:
            # Branch: <details> element
            # Count leaves under this branch
            leaf_count = count_leaves(child)
            parts.append(
                f'<details style="margin-left:{depth*1.5}rem">'
                f'<summary class="branch">'
                f'<span class="node-addr">[{label}]</span> '
                f'{leaf_count} terms</summary>\n'
                f'{render_tree_html(child, depth + 1, label)}'
                f'</details>\n'
            )
    return ''.join(parts)


def count_leaves(node):
    count = 0
    for digit in (0, 1, 2):
        if digit not in node:
            continue
        child = node[digit]
        if '_leaf' in child:
            count += 1
        else:
            count += count_leaves(child)
    return count


def compress_pages(pages):
    """Generate page reference links, compressing consecutive runs."""
    if not pages:
        return ''
    parts = []
    i = 0
    while i < len(pages):
        start = pages[i]
        end = start
        while i + 1 < len(pages) and pages[i + 1] == end + 1:
            i += 1
            end = pages[i]
        if start == end:
            parts.append(f'<a href="rawcorpus.html#p{start}">{start}</a>')
        elif end - start <= 2:
            for p in range(start, end + 1):
                parts.append(f'<a href="rawcorpus.html#p{p}">{p}</a>')
        else:
            parts.append(
                f'<a href="rawcorpus.html#p{start}">{start}</a>'
                f'\u2013<a href="rawcorpus.html#p{end}">{end}</a>'
            )
        i += 1
    return ' '.join(parts)


def write_corpus_html(pages, output_path):
    """Write paginated corpus as HTML with page anchors."""
    with open(output_path, 'w') as f:
        f.write(f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Corpus</title>
<style>{DARK_CSS}
.page {{ margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border); }}
.page-num {{ font-size: .7rem; color: var(--fg2); text-align: right; }}
pre {{ margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 12px; }}
:target {{ background: var(--highlight); }}
</style>
</head>
<body>
{TOGGLE_BTN}
<h1>Corpus</h1>
<p style="font-size:.8rem;color:var(--fg2)">{len(pages)} pages (A4 simulation, 12pt monospace, {LINES_PER_PAGE} lines/page)</p>
''')
        for i, page in enumerate(pages, 1):
            f.write(f'<div class="page" id="p{i}">\n')
            f.write(f'<div class="page-num">p. {i}</div>\n<pre>')
            for line in page:
                f.write(html.escape(line) + '\n')
            f.write('</pre>\n</div>\n')
        f.write('</body>\n</html>\n')


def write_appendix_html(tree, total_pages, output_path):
    """Write ternary tree appendix as HTML."""
    tree_html = render_tree_html(tree)
    with open(output_path, 'w') as f:
        f.write(f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Appendix &mdash; Word Index</title>
<style>{DARK_CSS}
details {{ margin: .3rem 0; }}
summary {{ cursor: pointer; padding: .2rem .4rem; border-radius: 4px; }}
summary:hover {{ background: var(--bg2); }}
.branch {{ font-size: .9rem; }}
.node-addr {{ font-family: monospace; color: var(--fg2); font-size: .75rem; }}
.leaf {{ padding: .2rem .4rem; margin: .2rem 0; }}
.pg-count {{ font-size: .75rem; color: var(--fg2); }}
.page-refs {{ font-size: .7rem; margin-top: .2rem; line-height: 1.8; }}
.page-refs a {{ margin-right: .3rem; }}
h1 {{ font-size: 1.4rem; border-bottom: 2px solid var(--border); padding-bottom: .5rem; }}
.intro {{ font-size: .85rem; color: var(--fg2); margin-bottom: 1.5rem; line-height: 1.6; }}
</style>
</head>
<body>
{TOGGLE_BTN}
<h1>Appendix &mdash; Word Index</h1>
<div class="intro">
Top 81 words by frequency, organized as a depth-4 ternary tree (3&sup4; = 81 leaves).<br>
Each leaf links to page locations in the <a href="rawcorpus.html">corpus</a> ({total_pages} pages).
</div>
{tree_html}
</body>
</html>
''')


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <corpus_dir> <output_dir>", file=sys.stderr)
        sys.exit(1)

    corpus_dir, output_dir = sys.argv[1], sys.argv[2]
    os.makedirs(output_dir, exist_ok=True)

    corpus_path = os.path.join(corpus_dir, 'rawcorpus.txt')
    freq_path = os.path.join(corpus_dir, 'lexicalfrequency.txt')

    # Load top 81 words (skip line 1 which is the "*" total)
    words = []
    with open(freq_path) as f:
        for line in f:
            parts = line.strip().split('"')
            if len(parts) >= 4:
                w = parts[1]
                if w == '*':
                    continue
                words.append(w)
                if len(words) >= 81:
                    break

    print(f"Top 81 words loaded: {words[0]}..{words[-1]}")

    # Paginate corpus
    print("Paginating corpus...")
    pages, line_to_page, raw_lines = paginate_corpus(corpus_path)
    print(f"  {len(pages)} pages, {len(raw_lines)} source lines")

    # Build word index
    print("Building word index...")
    word_index = build_word_index(raw_lines, line_to_page, words)
    for w in words[:5]:
        print(f"  '{w}': {len(word_index[w])} pages")

    # Build ternary tree
    words_with_pages = [(w, word_index[w]) for w in words]
    tree = build_tree(words_with_pages)

    # Write outputs
    corpus_out = os.path.join(output_dir, 'rawcorpus.html')
    appendix_out = os.path.join(output_dir, 'appendix.html')

    print(f"Writing {corpus_out}...")
    write_corpus_html(pages, corpus_out)

    print(f"Writing {appendix_out}...")
    write_appendix_html(tree, len(pages), appendix_out)

    print("Done.")


if __name__ == '__main__':
    main()
