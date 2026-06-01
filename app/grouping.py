"""Cluster processed videos into duplicate groups via union-find.

Two passes over the active, processed, non-pinned videos:

  * Exact: identical SHA-256 -> always the same group.
  * Perceptual: compare signatures with the configured matching method
    (combined/phash/dhash/ahash/whash) using bidirectional best-match frame
    comparison. When ``match_ignore_duration`` is on, every pair is compared
    (catches trimmed/padded copies); otherwise comparison is restricted to
    videos with similar runtimes (cheap pre-filter via duration buckets).

Videos flagged ``pinned_out`` ("not a duplicate") are skipped so a regroup
never re-merges something the user split out. ``group_id`` is assigned only to
clusters with >= 2 members; singletons get NULL.
"""
from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from typing import Dict, List

from sqlmodel import select

from . import config, hashing
from .db import get_session
from .models import State, Status, Video

logger = logging.getLogger("copycat.grouping")


class _UnionFind:
    def __init__(self, ids: List[int]):
        self.parent = {i: i for i in ids}

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def regroup() -> None:
    settings = config.get_settings()
    threshold = settings.similarity_threshold
    tol = settings.duration_tolerance
    method = settings.match_method
    ignore_duration = settings.match_ignore_duration

    with get_session() as session:
        videos = session.exec(
            select(Video).where(
                Video.status == Status.done,
                Video.state == State.active,
                Video.pinned_out == False,  # noqa: E712 - SQL boolean compare
            )
        ).all()

        ids = [v.id for v in videos]
        uf = _UnionFind(ids)
        by_id = {v.id: v for v in videos}
        # Parse each signature once up front; pairwise loops reuse these.
        parsed = {v.id: hashing.parse_signature(v.phash_signature) for v in videos}
        has_sig = {v.id for v in videos if any(parsed[v.id].values())}

        # Pass 1: exact SHA-256 duplicates.
        by_sha: Dict[str, List[int]] = defaultdict(list)
        for v in videos:
            if v.sha256:
                by_sha[v.sha256].append(v.id)
        for same in by_sha.values():
            for other in same[1:]:
                uf.union(same[0], other)

        # Pass 2: perceptual near-duplicates.
        def maybe_union(a: int, b: int) -> None:
            if uf.find(a) == uf.find(b):
                return
            if a not in has_sig or b not in has_sig:
                return
            if hashing.distance(parsed[a], parsed[b], method) <= threshold:
                uf.union(a, b)

        comparisons = 0
        if ignore_duration:
            # All-pairs: visual similarity only, runtime ignored.
            for a, b in itertools.combinations(ids, 2):
                comparisons += 1
                maybe_union(a, b)
        else:
            # Bucket by rounded duration; compare within a bucket and its neighbour.
            buckets: Dict[int, List[int]] = defaultdict(list)
            for v in videos:
                if v.duration:
                    buckets[int(round(v.duration / max(tol, 0.001)))].append(v.id)
            for key in sorted(buckets):
                candidates = buckets[key] + buckets.get(key + 1, [])
                for a, b in itertools.combinations(candidates, 2):
                    if abs((by_id[a].duration or 0) - (by_id[b].duration or 0)) > tol:
                        continue
                    comparisons += 1
                    maybe_union(a, b)

        # Assign group ids: only clusters with >= 2 members are real groups.
        clusters: Dict[int, List[int]] = defaultdict(list)
        for vid in ids:
            clusters[uf.find(vid)].append(vid)

        group_counter = 0
        assignments: Dict[int, int | None] = {}
        for members in clusters.values():
            if len(members) >= 2:
                group_counter += 1
                for m in members:
                    assignments[m] = group_counter
            else:
                assignments[members[0]] = None

        for v in videos:
            new_group = assignments.get(v.id)
            if v.group_id != new_group:
                v.group_id = new_group
                session.add(v)

        # Clear stale group ids on videos no longer eligible (pinned/non-active).
        stale = session.exec(
            select(Video).where(Video.group_id != None)  # noqa: E711
        ).all()
        for v in stale:
            if v.id not in assignments and v.group_id is not None:
                v.group_id = None
                session.add(v)

        session.commit()
        logger.info(
            "regroup: %s groups from %s videos (%s comparisons, method=%s, ignore_duration=%s)",
            group_counter, len(videos), comparisons, method, ignore_duration,
        )
