"""Pure-Python po -> lmo converter, faithful port of LuCI's po2lmo.c.

Semantics matched exactly:
  - key hash  = sfh_hash(raw msgid bytes, init=len)
  - val hash  = sfh_hash(raw msgstr bytes, init=len)
  - entries with key_id == val_id are skipped (self-translations)
  - entries with empty msgstr are skipped
  - blob is 4-byte padded between values
  - index sorted ascending by key_id, entries are 16 bytes (BE uint32 x4)
  - trailing uint32 BE = blob length
  - PO unescaping matches extract_string(): only \" and \\ are unescaped,
    other backslash sequences stay literal (no \n \t handling in po2lmo)

Usage:
  py -I po2lmo.py <input.po> <output.lmo>
  py -I po2lmo.py --verify <file.lmo>        dump entries
"""
import struct
import sys

MASK = 0xFFFFFFFF


def sfh_get16(d, i):
    return d[i] | (d[i + 1] << 8)


def sfh_hash(data: bytes, init: int) -> int:
    """Exact port of lmo.c sfh_hash (32-bit, little-endian reads)."""
    n = len(data)
    if n <= 0:
        return 0
    h = init & MASK
    rem = n & 3
    n >>= 2
    i = 0
    for _ in range(n):
        h = (h + sfh_get16(data, i)) & MASK
        tmp = ((sfh_get16(data, i + 2) << 11) ^ h) & MASK
        h = ((h << 16) ^ tmp) & MASK
        i += 4
        h = (h + (h >> 11)) & MASK

    if rem == 3:
        h = (h + sfh_get16(data, i)) & MASK
        h ^= (h << 16) & MASK
        b = data[i + 2]
        if b >= 128:
            b -= 256  # signed char
        h = (h ^ ((b << 18) & MASK)) & MASK
        h = (h + (h >> 11)) & MASK
    elif rem == 2:
        h = (h + sfh_get16(data, i)) & MASK
        h ^= (h << 11) & MASK
        h = (h + (h >> 17)) & MASK
    elif rem == 1:
        b = data[i]
        if b >= 128:
            b -= 256  # signed char
        h = (h + b) & MASK
        h ^= (h << 10) & MASK
        h = (h + (h >> 1)) & MASK

    h ^= (h << 3) & MASK
    h = (h + (h >> 5)) & MASK
    h ^= (h << 4) & MASK
    h = (h + (h >> 17)) & MASK
    h ^= (h << 25) & MASK
    h = (h + (h >> 6)) & MASK
    return h


def extract_string(line: str):
    """Port of po2lmo.c extract_string; returns bytes or None."""
    if line.startswith("#"):
        return None
    src = line.rstrip("\r\n")
    out = bytearray()
    off = -1
    esc = False
    for ch in src:
        if off == -1:
            if ch == '"':
                off = len(out)
        elif esc:
            if ch in ('"', "\\"):
                out.pop()  # drop the backslash appended earlier
            out.append(ord(ch) & 0xFF)
            esc = False
        elif ch == "\\":
            out.append(0x5C)
            esc = True
        elif ch != '"':
            out.append(ord(ch) & 0xFF)
        else:
            break
    return bytes(out) if off > -1 else None


def parse_po(path):
    """Return list of (msgid_bytes, msgstr_bytes) in file order."""
    pairs = []
    cur = None          # 'id' or 'str'
    bufs = {"id": bytearray(), "str": bytearray()}
    have = {"id": False, "str": False}
    # latin-1: 1 byte = 1 char, preserves raw UTF-8 bytes byte-for-byte
    with open(path, encoding="latin-1") as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith('msgid "'):
            if have["id"] or have["str"]:
                pairs.append((bytes(bufs["id"]), bytes(bufs["str"])))
                bufs = {"id": bytearray(), "str": bytearray()}
                have = {"id": False, "str": False}
            cur = "id"
        elif line.startswith("msgstr"):
            cur = "str"
        s = extract_string(line)
        if cur and s is not None and len(s) > 0:
            bufs[cur] += s
            have[cur] = True
        elif cur and s is not None and len(s) == 0:
            # empty literal e.g. msgid "" header — marks field present
            have[cur] = True if (not have[cur] and not bufs[cur]) else have[cur]
    if have["id"] or have["str"]:
        pairs.append((bytes(bufs["id"]), bytes(bufs["str"])))
    return pairs


def po_to_lmo(po_path, lmo_path):
    pairs = parse_po(po_path)
    blob = bytearray()
    entries = []
    for key, val in pairs:
        if not key or not val:
            continue  # header / untranslated
        kid = sfh_hash(key, len(key))
        vid = sfh_hash(val, len(val))
        if kid == vid:
            continue
        entries.append([kid, 1, len(blob), len(val)])
        blob += val
        pad = (4 - (len(val) % 4)) % 4
        blob += b"\x00" * pad
    entries.sort(key=lambda e: e[0])
    index = b"".join(struct.pack(">IIII", *e) for e in entries)
    with open(lmo_path, "wb") as f:
        f.write(bytes(blob))
        f.write(index)
        f.write(struct.pack(">I", len(blob)))
    print(f"{po_path}: {len(entries)} entries, blob {len(blob)} bytes -> {lmo_path}")


def verify_lmo(path):
    data = open(path, "rb").read()
    idx_off = struct.unpack(">I", data[-4:])[0]
    blob = data[:idx_off]
    index = data[idx_off:-4]
    assert len(index) % 16 == 0, "bad index size"
    print(f"{path}: {len(data)} bytes, blob {idx_off}, {len(index)//16} entries")
    prev = 0
    for i in range(0, len(index), 16):
        kid, vid, off, ln = struct.unpack(">IIII", index[i:i + 16])
        assert kid >= prev, f"index not sorted at entry {i//16}"
        prev = kid
        val = blob[off:off + ln]
        assert vid in (0, 1), f"unexpected val_id {vid} at entry {i//16}"
        assert kid != sfh_hash(val, len(val)) or kid == 0
        print(f"  key={kid:08x} val={vid:08x} off={off:6d} len={ln:5d}  {val[:64]!r}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--verify":
        verify_lmo(args[1])
    elif len(args) == 2:
        po_to_lmo(args[0], args[1])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
