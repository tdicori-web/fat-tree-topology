"""
failures.py
===========

Link-failure modeling for the fat-tree topology.

A "link failure" here means that a bidirectional link between two switches is
removed from the network. By default only *fabric* links (switch-to-switch
links in the edge/aggregation/core hierarchy) are eligible to fail. Host
access links are excluded by default, because failing a host's single uplink
simply isolates that one host and tells us nothing about the resilience of the
fabric itself -- it is the redundancy of the switch fabric that the fat-tree is
designed to provide, and therefore the quantity worth stressing.

The number of links removed is ``round(failure_rate * number_of_candidates)``,
and the specific links are chosen uniformly at random. A seed can be supplied
so that experiments are reproducible.
"""

from __future__ import annotations

import random

import networkx as nx


def candidate_links(G: nx.Graph, include_host_links: bool = False):
    """Return the list of links eligible to fail.

    Parameters
    ----------
    G : networkx.Graph
        A fat-tree graph whose edges carry a ``kind`` attribute
        ("host", "pod" or "core").
    include_host_links : bool
        If False (default), host access links are excluded, leaving only the
        switch-to-switch fabric links.
    """
    if include_host_links:
        return list(G.edges())
    return [(u, v) for u, v, d in G.edges(data=True) if d.get("kind") != "host"]


def apply_link_failures(G: nx.Graph, failure_rate: float, seed=None,
                        include_host_links: bool = False) -> nx.Graph:
    """Return a copy of ``G`` with a fraction of its links removed.

    Parameters
    ----------
    G : networkx.Graph
        The topology to perturb. ``G`` itself is not modified; a copy is
        returned.
    failure_rate : float
        Fraction of candidate links to remove, in [0, 1].
    seed : int or None
        Seed for the random number generator, for reproducibility.
    include_host_links : bool
        Whether host access links may fail (see ``candidate_links``).

    Returns
    -------
    networkx.Graph
        A new graph with the failed links removed.
    """
    if not 0.0 <= failure_rate <= 1.0:
        raise ValueError("failure_rate must be in [0, 1] (got %r)"
                         % (failure_rate,))

    rng = random.Random(seed)
    candidates = candidate_links(G, include_host_links=include_host_links)
    n_fail = round(failure_rate * len(candidates))

    G2 = G.copy()
    if n_fail > 0:
        failed = rng.sample(candidates, n_fail)
        G2.remove_edges_from(failed)
    return G2
