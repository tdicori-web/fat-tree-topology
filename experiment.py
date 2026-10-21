"""
experiment.py
=============

Experiment driver for the fat-tree assignment. Runs four experiments and saves
a plot for each into the output directory (default: ``results/``):

  1. (headline, advanced) Mean number of equal-cost (ECMP) shortest paths
     between host pairs as a function of the link-failure rate, for several
     values of k. Shows how the fat-tree's path diversity degrades under
     random fabric failures.

  2. Fraction of host pairs that remain connected as a function of the
     link-failure rate, for several values of k. A robustness / reachability
     view of the same perturbation.

  3. Mean shortest-path length (hops, over connected pairs) as a function of
     the link-failure rate. Shows when failures start to force longer detours.

  4. (basic) Number of hosts supported as a function of the switch port count
     k -- the closed-form k^3 / 4 scaling law.

Experiments 1-3 are Monte Carlo sweeps: at each failure rate the random
failure process is repeated ``--trials`` times and the metric is averaged;
the shaded band shows +/- one standard deviation across trials.

Usage
-----
    python experiment.py                 # full run, writes results/*.png
    python experiment.py --quick         # faster, coarser run (for smoke tests)
    python experiment.py --out myplots   # choose output directory
"""

from __future__ import annotations

import argparse
import os
import random

import matplotlib
matplotlib.use("Agg")  # headless / file-only backend
import matplotlib.pyplot as plt
import numpy as np

from fattree import FatTree
from failures import apply_link_failures
from metrics import sample_host_pairs, evaluate_pairs, hosts_supported


# --------------------------------------------------------------- sweep engine
def sweep_failures(k, failure_rates, trials, sample_pairs, base_seed):
    """Run the Monte Carlo failure sweep for one value of k.

    Returns a dict of arrays keyed by metric name; each array has one row per
    failure rate and one column per trial.
    """
    ft = FatTree(k)
    hosts = ft.hosts

    ecmp = np.zeros((len(failure_rates), trials))
    conn = np.zeros((len(failure_rates), trials))
    plen = np.full((len(failure_rates), trials), np.nan)

    for ri, rate in enumerate(failure_rates):
        for t in range(trials):
            # Distinct, reproducible seed per (k, rate, trial).
            seed = hash((base_seed, k, ri, t)) & 0xFFFFFFFF
            rng = random.Random(seed)
            pairs = sample_host_pairs(hosts, sample_pairs, rng)
            G = apply_link_failures(ft.G, rate, seed=seed)
            res = evaluate_pairs(G, pairs)
            ecmp[ri, t] = res["mean_ecmp"]
            conn[ri, t] = res["fraction_connected"]
            if res["mean_path_length"] is not None:
                plen[ri, t] = res["mean_path_length"]
    return {"ecmp": ecmp, "connected": conn, "path_length": plen}


def _mean_std(matrix):
    """Column-wise (per failure rate) mean and std, ignoring NaNs."""
    mean = np.nanmean(matrix, axis=1)
    std = np.nanstd(matrix, axis=1)
    return mean, std


# -------------------------------------------------------------------- plotting
def _plot_sweep(failure_rates, per_k, metric, ylabel, title, out_path,
                percent_x=True):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    x = np.array(failure_rates) * (100.0 if percent_x else 1.0)
    for k, data in per_k.items():
        mean, std = _mean_std(data[metric])
        line, = ax.plot(x, mean, marker="o", markersize=4, label=f"k = {k}")
        ax.fill_between(x, mean - std, mean + std, alpha=0.15,
                        color=line.get_color())
    ax.set_xlabel("Fabric link-failure rate (%)" if percent_x
                  else "Fabric link-failure rate")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  wrote {out_path}")


def plot_hosts_vs_k(k_values, out_path):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    hosts = [hosts_supported(k) for k in k_values]
    ax.plot(k_values, hosts, marker="o")
    for k, h in zip(k_values, hosts):
        ax.annotate(f"{h:,}", (k, h), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8)
    ax.set_xlabel("Switch port count k")
    ax.set_ylabel("Hosts supported  (k$^3$/4)")
    ax.set_title("Fat-tree scale: hosts supported vs. switch port count")
    ax.set_yscale("log")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  wrote {out_path}")


# ------------------------------------------------------------------------ main
def main(argv=None):
    p = argparse.ArgumentParser(description="Run fat-tree experiments.")
    p.add_argument("--out", default="results", help="output directory for plots.")
    p.add_argument("--seed", type=int, default=2026, help="base random seed.")
    p.add_argument("--quick", action="store_true",
                   help="coarser/faster run for smoke testing.")
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)

    if args.quick:
        k_sweep = [4, 8]
        failure_rates = [round(0.05 * i, 3) for i in range(0, 7)]  # 0..0.30
        trials = 5
        sample_pairs = 120
    else:
        k_sweep = [4, 8, 16]
        failure_rates = [round(0.025 * i, 3) for i in range(0, 13)]  # 0..0.30
        trials = 15
        sample_pairs = 300

    print(f"Config: k={k_sweep}, rates={failure_rates[0]}..{failure_rates[-1]} "
          f"({len(failure_rates)} pts), trials={trials}, "
          f"sample_pairs={sample_pairs}")

    per_k = {}
    for k in k_sweep:
        print(f"Sweeping k = {k} ...")
        per_k[k] = sweep_failures(k, failure_rates, trials, sample_pairs,
                                  args.seed)

    print("Generating plots:")
    _plot_sweep(failure_rates, per_k, "ecmp",
                "Mean ECMP shortest paths per host pair",
                "Path diversity vs. link-failure rate",
                os.path.join(args.out, "ecmp_vs_failure.png"))
    _plot_sweep(failure_rates, per_k, "connected",
                "Fraction of host pairs connected",
                "Reachability vs. link-failure rate",
                os.path.join(args.out, "connectivity_vs_failure.png"))
    _plot_sweep(failure_rates, per_k, "path_length",
                "Mean shortest-path length (hops)",
                "Path length vs. link-failure rate",
                os.path.join(args.out, "pathlen_vs_failure.png"))

    plot_hosts_vs_k([4, 8, 16, 24, 32, 48],
                    os.path.join(args.out, "hosts_vs_k.png"))

    print("Done.")


if __name__ == "__main__":
    main()
