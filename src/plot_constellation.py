#!/usr/bin/env python3
"""Build the constellation-vs-SNR grid figure from dm_rx npz captures."""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    argv = sys.argv[1:]
    if not argv:
        print("usage: plot_constellation.py <snr1.npz> [more.npz ...] [--out fig.png]")
        sys.exit(1)
    out = "constellation-vs-snr.png"
    if "--out" in argv:
        index = argv.index("--out")
        if index + 1 >= len(argv):
            raise SystemExit("--out requires a filename")
        out = argv[index + 1]
        files = argv[:index] + argv[index + 2:]
    else:
        files = argv
    if not files:
        raise SystemExit("provide at least one .npz capture")

    runs = []
    for f in sorted(files):
        d = np.load(f)
        runs.append({
            "mod": str(d["mod"]),
            "snr": float(d["snr_db"]),
            "evm": float(d["evm"]),
            "syms": d["symbols"],
            "points": d["points"],
            "gain": float(d["gain"]),
            "file": os.path.basename(f),
        })

    mods = sorted({r["mod"] for r in runs})
    snrs = sorted({r["snr"] for r in runs}, reverse=True)

    fig, axes = plt.subplots(len(mods), len(snrs), figsize=(4 * len(snrs), 4 * len(mods)),
                             dpi=120, squeeze=False)
    for i, m in enumerate(mods):
        for j, s in enumerate(snrs):
            ax = axes[i][j]
            run = next((r for r in runs if r["mod"] == m and abs(r["snr"] - s) < 1e-6), None)
            if run is None:
                ax.axis("off")
                continue
            syms = run["syms"]
            # Normalize to the constellation's radius: the receiver applies an
            # arbitrary overall scale/phase, so fit a complex gain that maps the
            # received cloud onto the ideal points before plotting.
            pts = run["points"]
            dd = np.abs(syms[:, None] - pts[None, :])
            assigned = pts[np.argmin(dd, axis=1)]
            g = np.vdot(assigned, syms) / np.vdot(assigned, assigned)
            syms = syms / g
            ax.scatter(syms.real, syms.imag, s=1.5, alpha=0.4, lw=0)
            ax.scatter(pts.real, pts.imag, s=30, marker="+", color="red")
            ax.set_title("%s, SNR ~%.1f dB (EVM %.1f%%)"
                         % (m.upper(), s, run["evm"] * 100), fontsize=10)
            lim = 1.7
            ax.set_xlim(-lim, lim)
            ax.set_ylim(-lim, lim)
            ax.set_aspect("equal")
            ax.grid(alpha=0.3)
            if j == 0:
                ax.set_ylabel(m.upper())
            else:
                ax.set_ylabel("")
            if i == len(mods) - 1:
                ax.set_xlabel("I")
            else:
                ax.set_xlabel("")

    fig.suptitle("Narrowband constellation vs SNR (measured via EVM)", fontsize=13)
    fig.savefig(out, bbox_inches="tight")
    print("saved", out)


if __name__ == "__main__":
    main()
