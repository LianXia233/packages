"""Scan a LuCI .po file against the app source tree.

Reports:
  1. msgids that no longer match any string in the sources (broken wrapping)
  2. source strings (from _('...') calls) that have no msgid in the po
  3. entries flagged fuzzy

Usage: py -I scan_po.py <app_dir>
"""
import difflib
import json
import os
import re
import sys

APP = sys.argv[1]
PO = os.path.join(APP, "po", "zh_Hans", "homeproxy.po")


def po_unescape(s):
    return (s.replace('\\"', '"').replace("\\\\", "\x00")
             .replace("\\n", "\n").replace("\\t", "\t").replace("\x00", "\\"))


def js_unescape(s):
    return (s.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\x00")
             .replace("\\n", "\n").replace("\\t", "\t").replace("\x00", "\\"))


def parse_po(path):
    """Return list of dicts: {'comments': [...], 'msgid': str, 'msgstr': str, 'fuzzy': bool}"""
    entries = []
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#,") and "fuzzy" in line:
            # attach to next entry
            j = i + 1
            while j < len(lines) and not lines[j].startswith("msgid"):
                j += 1
            # fallthrough: parse entry from j with fuzzy flag
            entries.append(parse_entry(lines, j, fuzzy=True))
            i = j
            # skip past entry
            i = skip_entry(lines, i)
            continue
        if line.startswith("msgid"):
            entries.append(parse_entry(lines, i, fuzzy=False))
            i = skip_entry(lines, i)
            continue
        i += 1
    return entries


def parse_entry(lines, start, fuzzy):
    comments = []
    i = start
    # collect preceding comment lines
    j = start - 1
    while j >= 0 and (lines[j].startswith("#") or lines[j].strip() == ""):
        if lines[j].startswith("#"):
            comments.insert(0, lines[j])
        j -= 1
    msgid_parts, msgstr_parts, in_str = [], [], None
    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid ") and in_str is None:
            in_str = "id"; msgid_parts.append(line[6:])
        elif line.startswith("msgstr ") and in_str == "id":
            in_str = "str"; msgstr_parts.append(line[7:])
        elif line.startswith('"') and in_str == "id":
            msgid_parts.append(line)
        elif line.startswith('"') and in_str == "str":
            msgstr_parts.append(line)
        elif line.startswith("#") and in_str is None:
            pass  # handled above
        else:
            break
        i += 1
    def join(parts):
        out = []
        for p in parts:
            p = p.strip()
            if len(p) >= 2 and p.startswith('"') and p.endswith('"'):
                out.append(p[1:-1])
            else:
                out.append(p)
        return po_unescape("".join(out))
    return {"msgid": join(msgid_parts), "msgstr": join(msgstr_parts),
            "fuzzy": fuzzy, "comments": comments, "line": start + 1}


def skip_entry(lines, i):
    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid") or line.startswith('"') or line.startswith("msgstr"):
            i += 1
            continue
        break
    return i


def extract_source_strings(base=None):
    """Extract literals from _('...') / _("...") calls in js/uc/htm files."""
    base = base or APP
    cands = {}
    rx = re.compile(r"""_\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)')""")
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "po")]
        for fn in files:
            if not fn.endswith((".js", ".uc", ".htm", ".lua")):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            for m in rx.finditer(text):
                lit = m.group(1) if m.group(1) is not None else m.group(2)
                s = js_unescape(lit)
                if s and s not in cands:
                    cands[s] = os.path.relpath(path, base)
    return cands


def main():
    entries = parse_po(PO)
    cands = extract_source_strings()
    haystack = []
    for root, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in (".git", "po")]
        for fn in files:
            path = os.path.join(root, fn)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    haystack.append(f.read())
            except OSError:
                pass
    hay = "\n".join(haystack)

    print(f"po entries: {len(entries)}, source _() literals: {len(cands)}\n")

    broken = []
    fuzzy = [e for e in entries if e["fuzzy"]]
    for e in entries:
        if e["msgid"] and e["msgid"] not in hay:
            broken.append(e)

    print(f"=== [1] msgid NOT found in sources (broken/stale): {len(broken)} ===")
    for e in broken:
        # try to find closest source candidate
        best, score = None, 0.0
        flat_id = " ".join(e["msgid"].split())
        for c in cands:
            flat_c = " ".join(c.split())
            r = difflib.SequenceMatcher(None, flat_id, flat_c).ratio()
            if r > score:
                best, score = c, r
        print(f'- po line {e["line"]}: {e["msgid"][:80]!r}')
        print(f'  closest source ({score:.3f}, file {cands.get(best, "?")}): {best[:80]!r}')
        print(f'  msgstr: {e["msgstr"][:60]!r}')

    print(f"\n=== fuzzy entries: {len(fuzzy)} ===")
    for e in fuzzy:
        print(f'- po line {e["line"]}: {e["msgid"][:60]!r}')

    missing = [c for c in cands if c not in {e["msgid"] for e in entries}]
    print(f"\n=== [2] source strings with NO po entry (untranslated): {len(missing)} ===")
    for c in sorted(missing):
        print(f'- [{cands[c]}] {c[:100]!r}')


if __name__ == "__main__":
    main()
