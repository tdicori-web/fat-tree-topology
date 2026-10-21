"""
metrics.py
==========

Structural and path-based metrics used to analyze the fat-tree topology, both
in its pristine state and after link failures have been applied.

All path metrics operate on a *sample* of random host pairs rather than on all
O(H^2) pairs, which keeps the experiments tractable for large ``k`` while still
producing stable averages. The sampling function is shared so that every metric
in a single experiment is evaluated on exactly the same set of pairs.
"""

from __future__ import annotations

import random

import networkx as nx

from fattree import shortest_path_stats


def hosts_supported(k: int) -> int:
    """Closed-form number of hosts a k-ary fat-tree supports: k^3 / 4."""
    return k ** 3 // 4


def sample_host_pairs(hosts, n_pairs: int, rng: random.Random):
    """Sample ``n_pairs`` distinct unordered host pairs uniformly at random.

    If the network is small enough that the requested number of pairs exceeds
    the number of available distinct pairs, every distinct pair is returned.
    """
    h = list(hosts)
    max_pairs = len(h) * (len(h) - 1) // 2
    n_pairs = min(n_pairs, max_pairs)

    seen = set()
    pairs = []
    while len(pairs) < n_pairs:
        a, b = rng.sample(h, 2)
        key = (a, b) if a <= b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((a, b))
    return pairs


def average_ecmp_paths(G: nx.Graph, pairs) -> float:
    """Mean number of equal-cost shortest paths over the given host pairs.

    Disconnected pairs contribute 0 paths, so this metric captures both the
    loss of path diversity and outright disconnection caused by failures.
    """
    if not pairs:
        return 0.0
    total = 0
    for src, dst in pairs:
        n_paths, _ = shortest_path_stats(G, src, dst)
        total += n_paths
    return total / len(pairs)


def fraction_connected(G: nx.Graph, pairs) -> float:
    """Fraction of host pairs that still have at least one path between them."""
    if not pairs:
        return 0.0
    connected = 0
    for src, dst in pairs:
        n_paths, _ = shortest_path_stats(G, src, dst)
        if n_paths > 0:
            connected += 1
    return connected / len(pairs)


def average_path_length(G: nx.Graph, pairs):
    """Mean shortest-path length (in hops) over *connected* host pairs.

    Returns ``None`` if no sampled pair is connected. Only connected pairs are
    averaged, since the distance to an unreachable host is undefined.
    """
    if not pairs:
        return None
    total = 0
    counted = 0
    for src, dst in pairs:
        n_paths, dist = shortest_path_stats(G, src, dst)
        if n_paths > 0 and dist is not None:
            total += dist
            counted += 1
    if counted == 0:
        return None
    return total / counted


def evaluate_pairs(G: nx.Graph, pairs) -> dict:
    """Evaluate all path metrics in a single pass over the sampled pairs.

    Runs exactly one breadth-first search per pair (instead of one per metric),
    and derives the mean ECMP path count, the fraction of connected pairs, and
    the mean shortest-path length (over connected pairs) together. This is the
    efficient path used by the experiment sweeps.
    """
    if not pairs:
        return {"mean_ecmp": 0.0, "fraction_connected": 0.0,
                "mean_path_length": None}
    total_paths = 0
    connected = 0
    total_len = 0
    for src, dst in pairs:
        n_paths, dist = shortest_path_stats(G, src, dst)
        total_paths += n_paths
        if n_paths > 0:
            connected += 1
            total_len += dist
    return {
        "mean_ecmp": total_paths / len(pairs),
        "fraction_connected": connected / len(pairs),
        "mean_path_length": (total_len / connected) if connected else None,
    }


def switches_with_multiple_failed_links(full_G: nx.Graph, failed_G: nx.Graph,
                                        threshold: int = 2) -> int:
    """Count switches that lost at least ``threshold`` fabric links.

    Compares a pristine graph against a post-failure graph and counts switch
    nodes whose fabric degree dropped by ``threshold`` or more.
    """
    count = 0
    for n, d in full_G.nodes(data=True):
        if d["tier"] == "host":
            continue
        before = full_G.degree(n)
        after = failed_G.degree(n) if n in failed_G else 0
        if before - after >= threshold:
            count += 1
    return count
