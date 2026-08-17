"""
iq.py — Complex-plane geometry for slow-time phasors.

Everything here treats the slow-time signal as a shape in the I/Q plane
rather than a phase sequence: finding the circle it traces, removing the
clutter offset that shifts that circle off origin, and reporting how much
of a loop it actually swept.

Prediction helpers at the bottom convert between displacement and
modulation index, so you can tell before a capture what the constellation
should look like and how close the unwrap will run to its limit.

No plotting, no side effects on import.
"""

import numpy as np

from vmd3lib.config import FS_SLOW, LAMBDA_M

LAMBDA_MM = LAMBDA_M * 1000.0


def fit_circle(sig):
    """
    Least-squares circle fit (Kasa) to a complex slow-time phasor.

    Returns (center, radius) with center complex. Solves the linearized
    form x^2 + y^2 = 2ax + 2by + c, which is a plain lstsq and needs no
    initial guess.

    Well conditioned when the phasor sweeps a decent fraction of a loop.
    Below ~90 degrees of arc the center estimate wanders badly; at the
    strokes in this experiment (2-3 full revolutions) it's very stable.
    """
    x, y = np.real(sig), np.imag(sig)
    A = np.column_stack([2.0 * x, 2.0 * y, np.ones_like(x)])
    b = x ** 2 + y ** 2
    a_, b_, c_ = np.linalg.lstsq(A, b, rcond=None)[0]
    center = complex(a_, b_)
    radius = float(np.sqrt(c_ + a_ ** 2 + b_ ** 2))
    return center, radius


def remove_dc(sig, method='mean'):
    """
    Remove the static-clutter offset that shifts the I/Q circle off origin.

    'mean'   : subtract the sample mean. Correct when the phasor sweeps
               most of a loop, since its own contribution then averages to
               near zero and what's left is clutter.
    'circle' : subtract the fitted circle center. Slower, but the right
               answer when the arc is short and the mean would eat signal.
    None     : passthrough.

    Taking np.angle() of an off-center arc gives an amplitude-dependent,
    nonlinear phase estimate with spurious harmonics baked in — it looks
    like a real measurement and isn't. This is the step that prevents that.
    """
    if method is None:
        return sig
    if method == 'mean':
        return sig - np.mean(sig)
    if method == 'circle':
        center, _ = fit_circle(sig)
        return sig - center
    raise ValueError(f"method must be 'mean', 'circle', or None (got {method!r})")


def arc_span_deg(sig):
    """
    Total angular sweep of the phasor, in degrees (peak-to-peak of the
    unwrapped phase). Equals 2*beta for clean sinusoidal motion.

    Center the signal first — the angle is only meaningful about the true
    circle center. Noise can inject spurious unwrap jumps, so treat this
    as a diagnostic rather than a measurement.
    """
    return float(np.ptp(np.unwrap(np.angle(sig)))) * 180.0 / np.pi


def revolutions(sig):
    """
    How many full circles the phasor traces. Below ~0.25 you have a short
    arc (circle fitting is unreliable); above ~1 you have a closed loop.
    """
    return arc_span_deg(sig) / 360.0


def beta_from_displacement(disp_mm):
    """
    Modulation index for a given peak-to-peak displacement.
    beta = 2*pi*D/lambda. Half the total phase swing.
    """
    return 2.0 * np.pi * disp_mm / LAMBDA_MM


def displacement_from_beta(beta):
    """Inverse of beta_from_displacement — peak-to-peak mm."""
    return beta * LAMBDA_MM / (2.0 * np.pi)


def predicted_phase_step(disp_mm, freq_hz, fs=FS_SLOW):
    """
    Largest expected frame-to-frame phase jump, in radians:
    4*pi^2*D*f / (lambda*fs). Compare against max_phase_step() on real data.

    Must stay under pi or np.unwrap guesses wrong and every displacement
    value afterward carries a fixed 2*pi offset. Under pi/2 also survives a
    single dropped frame, since a drop doubles the effective time step.
    """
    return 4.0 * np.pi ** 2 * disp_mm * freq_hz / (LAMBDA_MM * fs)