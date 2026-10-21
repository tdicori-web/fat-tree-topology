"""
fattree.py
==========

Generator for a k-ary fat-tree data center network topology, following the
design of:

    M. Al-Fares, A. Loukissas, and A. Vahdat, "A scalable, commodity data
    center network architecture," SIGCOMM Comput. Commun. Rev., vol. 38,
    no. 4, pp. 63-74, Oct. 2008. doi:10.1145/1402946.1402967

The topology is a three-tier hierarchy (edge / aggregation / core) built from
identical commodity switches that each have ``k`` ports. ``k`` must be even.

Structural properties for a given ``k`` (k even):

    hosts               = k^3 / 4
    core switches       = (k/2)^2
    aggregation switches= k^2 / 2
    edge switches       = k^2 / 2
    total switches      = 5 * k^2 / 4
    pods                = k
    ECMP paths between two hosts in different pods = (k/2)^2

Wiring rules
------------
* The network is organized into ``k`` pods. Each pod contains ``k/2`` edge
  switches and ``k/2`` aggregation switches, connected as a complete bipartite
  graph (every edge switch connects to every aggregation switch in its pod).
* Each edge switch connects to ``k/2`` hosts below it.
* The ``(k/2)^2`` core switches are arranged as a (k/2) x (k/2) grid indexed
  ``(i, j)``. The i-th aggregation switch of *every* pod connects to the whole
  i-th row of the core grid, i.e. to core switches ``(i, 0) .. (i, k/2 - 1)``.
  Consequently each core switch ``(i, j)`` connects to the i-th aggregation
  switch in each of the ``k`` pods, using all ``k`` of its ports.

The resulting graph is returned as a ``networkx.Graph``. Every node carries a
``tier`` attribute in {"core", "aggregation", "edge", "host"}. Nodes are
tuples so their role and position are self-documenting:

    ("core", i, j)          core switch at grid position (i, j)
    ("agg",  pod, a)        a-th aggregation switch in pod ``pod``
    ("edge", pod, e)        e-th edge switch in pod ``pod``
    ("host", pod, e, h)     h-th host under edge switch ("edge", pod, e)
"""

from __future__ import annotations

import argparse
from collections import deque

import networkx as nx


class FatTree:
    """A k-ary fat-tree topology.

    Parameters
    ----------
    k : int
        Switch port count. Must be a positive even integer. Determines the
        whole topology (number of pods, switches and hosts).
    """

    def __init__(self, k: int):
        if not isinstance(k, int) or k <= 0 or k % 2 != 0:
            raise ValueError("k must be a positive even integer (got %r)" % (k,))
        self.k = k
        self.half = k // 2
        self.G = nx.Graph() # undirected graph, since the fat-tree is symmetric and bidirectional
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self) -> nx.Graph:
        k = self.k
        half = self.half

        # Core switches: a (k/2) x (k/2) grid.
        for i in range(half):
            for j in range(half):
                self.G.add_node(("core", i, j), tier="core")

        for pod in range(k):
            # Aggregation and edge switches of this pod.
            for a in range(half):
                self.G.add_node(("agg", pod, a), tier="aggregation")
            for e in range(half):
                self.G.add_node(("edge", pod, e), tier="edge")

            # Intra-pod: complete bipartite between edge and aggregation.
            for e in range(half):
                for a in range(half):
                    self.G.add_edge(("edge", pod, e), ("agg", pod, a),
                                    kind="pod")

            # Hosts hang off each edge switch.
            for e in range(half):
                for h in range(half):
                    host = ("host", pod, e, h)
                    self.G.add_node(host, tier="host")
                    self.G.add_edge(("edge", pod, e), host, kind="host")

            # Aggregation -> core: agg ``a`` connects to core row ``a``.
            for a in range(half):
                for j in range(half):
                    self.G.add_edge(("agg", pod, a), ("core", a, j),
                                    kind="core")

        return self.G

    # ------------------------------------------------------------- accessors
    def nodes_of_tier(self, tier: str):
        """Return the list of nodes belonging to a given tier."""
        return [n for n, d in self.G.nodes(data=True) if d["tier"] == tier]

    @property
    def hosts(self):
        return self.nodes_of_tier("host")

    @property
    def switches(self):
        return [n for n, d in self.G.nodes(data=True) if d["tier"] != "host"]

    def fabric_links(self):
        """Switch-to-switch links (the network fabric), excluding host links."""
        return [(u, v) for u, v, d in self.G.edges(data=True)
                if d.get("kind") != "host"]

    # --------------------------------------------------------------- summary
    def expected_counts(self) -> dict:
        """Closed-form structural counts, independent of the built graph."""
        k, half = self.k, self.half
        return {
            "pods": k,
            "hosts": k ** 3 // 4,
            "core_switches": half ** 2,
            "aggregation_switches": k ** 2 // 2,
            "edge_switches": k ** 2 // 2,
            "total_switches": 5 * k ** 2 // 4,
            "ecmp_paths_inter_pod": half ** 2,
        }

    def summary(self) -> str:
        c = self.expected_counts()
        lines = [
            f"Fat-tree topology (k = {self.k})",
            f"  pods                     : {c['pods']}",
            f"  hosts                    : {c['hosts']}",
            f"  core switches            : {c['core_switches']}",
            f"  aggregation switches     : {c['aggregation_switches']}",
            f"  edge switches            : {c['edge_switches']}",
            f"  total switches           : {c['total_switches']}",
            f"  ECMP paths (inter-pod)   : {c['ecmp_paths_inter_pod']}",
            f"  graph nodes / edges      : {self.G.number_of_nodes()} / "
            f"{self.G.number_of_edges()}",
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------- helpers
def shortest_path_stats(G: nx.Graph, src, dst):
    """Return (number_of_shortest_paths, distance) between ``src`` and ``dst``.

    A single breadth-first search computes both the hop distance and the number
    of distinct equal-cost (shortest) paths, by accumulating path counts along
    the BFS frontier (standard counting of shortest paths in an unweighted
    graph). If ``dst`` is unreachable, returns (0, None).
    """
    if src == dst:
        return 1, 0
    dist = {src: 0}
    count = {src: 1}
    q = deque([src])
    while q:
        u = q.popleft()
        du = dist[u]
        for w in G.neighbors(u):
            if w not in dist:
                dist[w] = du + 1
                count[w] = count[u]
                q.append(w)
            elif dist[w] == du + 1:
                count[w] += count[u]
    if dst not in dist:
        return 0, None
    return count[dst], dist[dst]


# ------------------------------------------------------------------------ CLI
def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate and inspect a k-ary fat-tree topology.")
    p.add_argument("-k", "--k", type=int, required=True,
                   help="switch port count (positive even integer).")
    p.add_argument("-f", "--failure", type=float, default=0.0,
                   help="fraction of fabric (switch-switch) links to fail, "
                        "in [0, 1]. Default 0.0 (no failures).")
    p.add_argument("-s", "--seed", type=int, default=None,
                   help="random seed for reproducible link failures.")
    p.add_argument("--sample-pairs", type=int, default=200,
                   help="number of random host pairs sampled for the path "
                        "statistics printed in the summary.")
    return p


def main(argv=None):
    args = _build_cli().parse_args(argv)
    ft = FatTree(args.k)
    G = ft.G

    print(ft.summary())

    if args.failure and args.failure > 0.0:
        # Local import to keep fattree.py usable on its own.
        from failures import apply_link_failures
        G = apply_link_failures(G, args.failure, seed=args.seed)
        removed = ft.G.number_of_edges() - G.number_of_edges()
        print(f"\nApplied link failures: rate = {args.failure:.3f}, "
              f"removed {removed} fabric links.")

    # Quick path statistics over a sample of random host pairs.
    import random
    from metrics import sample_host_pairs, average_ecmp_paths, \
        fraction_connected, average_path_length

    rng = random.Random(args.seed)
    pairs = sample_host_pairs(ft.hosts, args.sample_pairs, rng)
    print("\nPath statistics over %d random host pairs:" % len(pairs))
    print(f"  mean ECMP shortest paths : "
          f"{average_ecmp_paths(G, pairs):.3f}")
    print(f"  fraction connected       : "
          f"{fraction_connected(G, pairs):.3f}")
    apl = average_path_length(G, pairs)
    apl_str = "n/a" if apl is None else f"{apl:.3f}"
    print(f"  mean path length (hops)  : {apl_str}")


if __name__ == "__main__":
    main()
