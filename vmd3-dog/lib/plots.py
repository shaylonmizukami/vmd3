"""Shared plot setup for range-angle maps."""

import matplotlib.pyplot as plt

from config import LEAKAGE_CUTOFF_M

def draw_range_angle(ax, db, ranges, angles, floor, max_range=None):
    """Draw a range-angle map on an existing axis and return the mesh."""
    mesh = ax.pcolormesh(angles, ranges, db, shading="nearest", cmap="inferno", vmin=floor, vmax=0)
    ax.axhline(LEAKAGE_CUTOFF_M, color="white", linestyle=":", linewidth=1)
    ax.set_ylim(0, max_range or ranges[-1])
    ax.set_xlabel("Angle (deg, + is right)")
    ax.set_ylabel("Range (m)")
    return mesh

def range_angle_axes(db, ranges, angles, floor, max_range=None):
    """Draw a range-angle map in a new figure and return (fig, ax, mesh)."""
    fig, ax = plt.subplots(figsize=(8, 6))
    mesh = draw_range_angle(ax, db, ranges, angles, floor, max_range)
    fig.colorbar(mesh, ax=ax, label="dB rel. strongest return past leakage")
    return fig, ax, mesh
