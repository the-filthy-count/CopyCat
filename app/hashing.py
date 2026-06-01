"""Exact (SHA-256) and perceptual hashing + similarity distance.

Perceptual fingerprints are *multi-signal*: for each filmstrip frame we store
several complementary image hashes (pHash, dHash, aHash, wHash). Different
hashes are robust to different distortions, so combining them catches more
re-encodes/resizes than any single one.

Signature JSON formats:
  v2 (current): {"v": 2, "frames": [["<p>", "<d>", "<a>", "<w>"], ...]}
  v1 (legacy) : ["<phash>", "<phash>", ...]   -> read as pHash only

Frames are compared by *best match* (each frame in A paired with its closest
frame in B, and vice-versa) rather than by index, so trimmed/offset copies
still line up.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

import imagehash
from PIL import Image

_HASH_BITS = 64  # 8x8 hashes -> 64 bits for phash/dhash/ahash/whash

# Order of hashes stored per frame in the v2 signature.
_METHOD_KEYS = ("p", "d", "a", "w")
_HASHERS = {
    "p": imagehash.phash,
    "d": imagehash.dhash,
    "a": imagehash.average_hash,
    "w": imagehash.whash,
}

# A matching "method" maps to the hash key(s) whose distances are averaged.
METHODS: Dict[str, List[str]] = {
    "combined": ["p", "d"],
    "phash": ["p"],
    "dhash": ["d"],
    "ahash": ["a"],
    "whash": ["w"],
}


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Stream a full SHA-256 of the file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _frame_hashes(path: Path) -> List[str]:
    """All configured perceptual hashes for one image, as hex strings."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        return [str(_HASHERS[k](img)) for k in _METHOD_KEYS]


def build_signature(frame_paths: List[Path]) -> str:
    """Build a v2 multi-signal signature from a list of frame images."""
    frames = [_frame_hashes(p) for p in frame_paths]
    return json.dumps({"v": 2, "frames": frames})


ParsedSig = Dict[str, List[imagehash.ImageHash]]


def parse_signature(sig: Optional[str]) -> ParsedSig:
    """Parse a signature into {hash_key: [ImageHash, ...]} lists.

    Handles both the v2 multi-signal format and the legacy v1 pHash list.
    """
    out: ParsedSig = {k: [] for k in _METHOD_KEYS}
    if not sig:
        return out
    data = json.loads(sig)
    if isinstance(data, list):  # v1: list of pHash hex strings
        out["p"] = [imagehash.hex_to_hash(h) for h in data]
        return out
    for frame in data.get("frames", []):
        for idx, key in enumerate(_METHOD_KEYS):
            if idx < len(frame) and frame[idx]:
                out[key].append(imagehash.hex_to_hash(frame[idx]))
    return out


def is_legacy_signature(sig: Optional[str]) -> bool:
    """True if the signature lacks the multi-signal hashes (needs recompute)."""
    return bool(sig) and sig.lstrip().startswith("[")


def _best_match(a: List[imagehash.ImageHash], b: List[imagehash.ImageHash]) -> float:
    """Bidirectional best-match Hamming distance, normalized to [0, 1].

    For each frame in A we take its closest frame in B (and vice-versa), average
    each direction, and return the larger of the two so *both* sequences must
    align well — this curbs spurious one-directional matches.
    """
    if not a or not b:
        return 1.0
    a_to_b = sum(min(x - y for y in b) for x in a) / len(a)
    b_to_a = sum(min(y - x for x in a) for y in b) / len(b)
    return max(a_to_b, b_to_a) / _HASH_BITS


def distance(parsed_a: ParsedSig, parsed_b: ParsedSig, method: str = "combined") -> float:
    """Normalized [0, 1] perceptual distance for the chosen method.

    ``combined`` averages the pHash and dHash distances. If a required hash is
    missing (e.g. a legacy signature under a non-pHash method), that component
    falls back to pHash so comparison still works.
    """
    keys = METHODS.get(method, METHODS["combined"])
    dists: List[float] = []
    for key in keys:
        la, lb = parsed_a.get(key, []), parsed_b.get(key, [])
        if not la or not lb:
            # Fall back to pHash if this hash isn't available on both sides.
            la, lb = parsed_a.get("p", []), parsed_b.get("p", [])
        dists.append(_best_match(la, lb))
    return sum(dists) / len(dists) if dists else 1.0
