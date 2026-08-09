# Imports
import pandas as pd
import numpy as np 
import math
import matplotlib.pyplot as plt
import pathlib
import bio_radar.BioRadar as br
import os, re, glob
from scipy.signal import butter, filtfilt
from bio_radar.helper_functions import open_data, save_file, get_iq_plot_lims
from pathlib import Path
import json
from datetime import datetime
# Setup Dirs, Data, and variables
Select Data
datestring = "2026_04_16"

ROOT = pathlib.Path.cwd().parent     # adjust if repo is higher or deeper

DATA_DIR = ROOT / "data" 

OUT_DIR = ROOT / "outputs" / datestring
OUT_DIR.mkdir(parents=True, exist_ok=True)
Plotting/styling options
generate_filtered_plots = False
generate_cal_plots = False
generate_human_plots = True

title_fontsize = 28
axes_fontsize = 26
Define RCS calibration values. You can add to this using the data defined in the `Process Mover Data` section in the notebook.
import pathlib
import re
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# ==========================================================
# CALIBRATION SIGMA (AUTHORITATIVE VALUES)
# ==========================================================
# These MUST match your ground-truth script

SIGMA_CAL_VALS = {
    # frontend : { freq_hz : { plate_cm : sigma_cal_m2 } }
    "apa_circ": {
        2.4e9: {
            16: 0.822980,        # 16 cm × 20 cm plate, σ = 4π(0.16·0.20)²/λ²
            18: 1.042305,        # 18 cm × 20 cm plate (measured / trusted)
        },
    },
    "klc7": {
        24e9: {
            12: 18.09557368,     # 12 cm × 12.5 cm plate
        },
    },
}

def get_sigma_cal(frontend: str, freq_hz: float, plate_cm: int) -> float:
    try:
        return float(SIGMA_CAL_VALS[frontend][freq_hz][int(plate_cm)])
    except KeyError:
        raise ValueError(
            f"No sigma_cal defined for frontend={frontend}, freq={freq_hz}, "
            f"plate={plate_cm} cm"
        )


# ==========================================================
# 0) HARD-CODED CAL LOOKUPS
# ==========================================================
# Key structure:
#   CAL_LOOKUPS[frontend][(freq_hz, dist_m, plate_cm, pol, version)]
#     = {"ae": ..., "pe": ..., "r_cal": ...}
#
# pol      : "V" (vtx) or "H" (htx)
# version  : "old" (original RWW dataset) or "new" (current spreadsheet)
#
# Only "new" entries exist for dual-polarization. "old" is Vtx-only and
# retained so you can reproduce earlier RWW analysis.

CAL_LOOKUPS = {
    "apa_circ": {
        # -------- OLD (Vtx only, 18 cm plate, from original RWW notebook) --------
        (2.4e9, 0.5, 18, "V", "old"): {"ae": 1.016784, "pe": -0.184801, "r_cal": 0.021218},
        (2.4e9, 1.0, 18, "V", "old"): {"ae": 1.016784, "pe": -0.184801, "r_cal": 0.0084425},
        (2.4e9, 1.5, 18, "V", "old"): {"ae": 1.030959, "pe": -0.181748, "r_cal": 0.003762},
        (2.4e9, 2.0, 18, "V", "old"): {"ae": 1.030959, "pe": -0.181748, "r_cal": 0.0026070},  # reuse 1.5 m
        (2.4e9, 2.5, 18, "V", "old"): {"ae": 1.050839, "pe": -0.243994, "r_cal": 0.001457},
        (2.4e9, 3.0, 18, "V", "old"): {"ae": 1.050839, "pe": -0.243994, "r_cal": 0.0010883333333333334},  # reuse 2.5 m
        (2.4e9, 3.5, 18, "V", "old"): {"ae": 1.015314, "pe": -0.068505, "r_cal": 0.0007311},

        # -------- NEW (from current spreadsheet, 16 cm and 18 cm, V + H pol) --------
        # 16 cm plate @ 2.4 GHz
        (2.4e9, 1.0, 16, "V", "new"): {"ae": 0.9952740, "pe": -0.2268130, "r_cal": 0.0076980},
        (2.4e9, 1.0, 16, "H", "new"): {"ae": 1.0007840, "pe": -0.3107940, "r_cal": 0.0066230},
        (2.4e9, 1.5, 16, "V", "new"): {"ae": 0.9958280, "pe": -0.2458140, "r_cal": 0.0038400},
        (2.4e9, 1.5, 16, "H", "new"): {"ae": 1.0304990, "pe": -0.2700080, "r_cal": 0.0025420},

        # 18 cm plate @ 2.4 GHz
        (2.4e9, 1.0, 18, "V", "new"): {"ae": 0.9750610, "pe": -0.2299940, "r_cal": 0.0084320},
        (2.4e9, 1.0, 18, "H", "new"): {"ae": 1.0075660, "pe": -0.2885070, "r_cal": 0.0078250},
        (2.4e9, 1.5, 18, "V", "new"): {"ae": 0.9914610, "pe": -0.2361810, "r_cal": 0.0042060},
        (2.4e9, 1.5, 18, "H", "new"): {"ae": 1.0042100, "pe": -0.2958850, "r_cal": 0.0032870},
    },

    "klc7": {
        # -------- OLD (Vtx only, 12 cm plate, from original RWW notebook) --------
        (24e9, 0.5, 12, "V", "old"): {"ae": 1.052520, "pe": -0.320345, "r_cal": 0.003638},
        (24e9, 1.0, 12, "V", "old"): {"ae": 1.051620, "pe": -0.246630, "r_cal": 0.002317},
        (24e9, 1.5, 12, "V", "old"): {"ae": 1.043230, "pe": -0.307374, "r_cal": 0.001146},
        (24e9, 2.0, 12, "V", "old"): {"ae": 1.064989, "pe": -0.253940, "r_cal": 0.0007446},
        (24e9, 2.5, 12, "V", "old"): {"ae": 1.072112, "pe": -0.205930, "r_cal": 0.000439},
        (24e9, 3.0, 12, "V", "old"): {"ae": 1.063472, "pe": -0.177246, "r_cal": 0.0003212},
        (24e9, 3.5, 12, "V", "old"): {"ae": 1.064274, "pe": -0.188535, "r_cal": 0.000287},

        # -------- NEW (from current spreadsheet, 12 cm, V + H pol) --------
        (24e9, 1.0, 12, "V", "new"): {"ae": 0.9647550, "pe": -0.2805310, "r_cal": 0.0025000},
        (24e9, 1.0, 12, "H", "new"): {"ae": 0.9644790, "pe": -0.2628120, "r_cal": 0.0023320},
        (24e9, 1.5, 12, "V", "new"): {"ae": 0.9594140, "pe": -0.3003320, "r_cal": 0.0015220},
        (24e9, 1.5, 12, "H", "new"): {"ae": 0.9616220, "pe": -0.2799650, "r_cal": 0.0013280},
    },
}


def _cal_lookup(frontend, freq_hz, dist_m, plate_cm, pol, version):
    """Fetch the full cal record for one (frontend, freq, dist, plate, pol, version)."""
    key = (float(freq_hz), float(dist_m), int(plate_cm), pol.upper(), version.lower())
    try:
        return CAL_LOOKUPS[frontend][key]
    except KeyError as e:
        raise KeyError(
            f"Missing cal for frontend={frontend}, freq={freq_hz/1e9:g} GHz, "
            f"dist={dist_m} m, plate={plate_cm} cm, pol={pol}, version={version}"
        ) from e


def get_R_cal(frontend, freq_hz, dist_m, plate_cm, pol="V", version="new"):
    """Return r_cal (arc radius / A_cal)."""
    return float(_cal_lookup(frontend, freq_hz, dist_m, plate_cm, pol, version)["r_cal"])


def get_imbalance_coeffs(frontend, freq_hz, dist_m, plate_cm, pol="V", version="new"):
    """Return (A_e, phi_e)."""
    rec = _cal_lookup(frontend, freq_hz, dist_m, plate_cm, pol, version)
    return float(rec["ae"]), float(rec["pe"])
# Function Definitions
# ==========================================================
# 1) Filtering / DSP Utilities
# ==========================================================

def lowpass_python_safe(x, fc, fs, order=6, padtype="odd", trim_edges=True):
    """
    Safe zero-phase lowpass. Does NOT change data length.
    - If x is too short for filtfilt padding, returns x unchanged.
    - Optionally trims edge region that is most likely corrupted by padding.
    """
    x = np.asarray(x, float)
    if x.ndim != 1:
        x = x.ravel()

    nyq = fs / 2.0
    if not (0 < fc < nyq):
        raise ValueError(f"Cutoff fc must be between 0 and Nyquist. Got fc={fc}, Nyq={nyq}")

    b, a = butter(order, fc / nyq, btype="low", analog=False)
    padlen_default = 3 * (max(len(a), len(b)) - 1)

    if len(x) <= padlen_default:
        return x.copy()

    y = filtfilt(b, a, x, padtype=padtype, padlen=padlen_default)

    if trim_edges:
        y[:padlen_default] = y[padlen_default]
        y[-padlen_default:] = y[-padlen_default-1]

    return y


def apply_filter(df, fc=10.0, fs=1000.0, order=6):
    I = lowpass_python_safe(df["I"].to_numpy(), fc=fc, fs=fs, order=order)
    Q = lowpass_python_safe(df["Q"].to_numpy(), fc=fc, fs=fs, order=order)
    return pd.DataFrame({"I": I, "Q": Q})


# ==========================================================
# 2) File Discovery & Name Parsing
# ==========================================================

def parse_filename_v2(filepath):
    """
    Parse new-format radar filenames. Returns dict with:
      filepath, filename, subject, freq_hz, dist_m, gain, pol_tx,
      dtype, target, plate_cm, dset, is_cal
    """
    p = pathlib.Path(filepath)
    name = p.stem.lower()
    subject = p.parent.name.lower()

    if "2p4ghz" in name:
        freq_hz = 2.4e9
    elif "24ghz" in name:
        freq_hz = 24e9
    else:
        freq_hz = None

    m = re.search(r"_g(\d+)_", name)
    gain = int(m.group(1)) if m else None

    m = re.search(r"dtype_(cal|hum)", name)
    dtype = m.group(1) if m else None
    is_cal = (dtype == "cal")

    m = re.search(r"tgt_(.+?)_range_", name)
    target = m.group(1) if m else None

    plate_cm = None
    if target:
        m = re.search(r"plate(\d+(?:\.\d+)?)cm", target)
        if m:
            plate_cm = float(m.group(1))

    m = re.search(r"range_(\d+p?\d*)m", name)
    dist_m = float(m.group(1).replace("p", ".")) if m else None

    m = re.search(r"_([hv])tx_", name)
    pol_tx = m.group(1).upper() if m else None

    m = re.search(r"dset_(\d+)", name)
    dset = int(m.group(1)) if m else None

    return {
        "filepath": str(p), "filename": p.name, "subject": subject,
        "freq_hz": freq_hz, "dist_m": dist_m, "gain": gain, "pol_tx": pol_tx,
        "dtype": dtype, "target": target, "plate_cm": plate_cm,
        "dset": dset, "is_cal": is_cal,
    }


def discover_human_files(data_root, skip_dirs=("cal",)):
    """
    Walk data_root, skip subject folders listed in skip_dirs,
    return sorted list of CSV paths for all human subjects.
    """
    data_root = pathlib.Path(data_root)
    skip = {s.lower() for s in skip_dirs}
    files = []
    for subj_dir in sorted(data_root.iterdir()):
        if not subj_dir.is_dir():
            continue
        if subj_dir.name.lower() in skip:
            continue
        files.extend(sorted(subj_dir.glob("*.csv")))
    return [str(f) for f in files]


def get_subset(df_files, subject=None, dist_m=None, freq_hz=None,
               pol_tx=None, dset=None):
    """Return rows of df_files matching the given filters."""
    mask = pd.Series(True, index=df_files.index)
    if subject is not None:
        mask &= df_files["subject"] == subject.lower()
    if dist_m is not None:
        mask &= df_files["dist_m"] == float(dist_m)
    if freq_hz is not None:
        mask &= df_files["freq_hz"] == float(freq_hz)
    if pol_tx is not None:
        mask &= df_files["pol_tx"] == pol_tx.upper()
    if dset is not None:
        mask &= df_files["dset"] == int(dset)
    return df_files.loc[mask].reset_index(drop=True)


# ==========================================================
# 3) I/Q CSV Reading, Filtering & Saving
# ==========================================================

def read_iq_csv(path):
    """Reads CSV with columns I, Q (with or without headers)."""
    df = pd.read_csv(path)
    if "I" not in df.columns or "Q" not in df.columns:
        df.columns = ["I", "Q"]
    return df[["I", "Q"]].astype(float)


def filter_and_save_all(df_files, filtered_dir, fc=10.0, fs=1000.0,
                        order=6, overwrite=False, suffix="_filtered"):
    """
    Filters all CSVs listed in df_files, saves to 'filtered_dir'.
    Returns updated DataFrame with a 'filtered_path' column.
    """
    filtered_dir = pathlib.Path(filtered_dir)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    filtered_paths = []
    for _, row in df_files.iterrows():
        src = pathlib.Path(row.filepath)
        dst = filtered_dir / src.name.replace(".csv", f"{suffix}.csv")

        if dst.exists() and not overwrite:
            filtered_paths.append(str(dst))
            continue

        df = read_iq_csv(src)
        df_filt = apply_filter(df, fc=fc, fs=fs, order=order)
        df_filt.to_csv(dst, index=False)
        filtered_paths.append(str(dst))

    out = df_files.copy()
    out["filtered_path"] = filtered_paths
    return out


# ==========================================================
# 4) Plotting Helpers
# ==========================================================

def plot_raw_vs_filtered(row, fs=1000.0):
    """Compare raw and filtered I/Q from a df_files row. QA tool."""
    raw_path = pathlib.Path(row["filepath"])
    fil_path = row.get("filtered_path", None)
    if pd.isna(fil_path) or not fil_path:
        raise ValueError("Filtered path not found. Run filtering first.")
    fil_path = pathlib.Path(fil_path)

    df_raw = read_iq_csv(raw_path)
    df_fil = read_iq_csv(fil_path)
    t_raw = np.arange(len(df_raw)) / fs
    t_fil = np.arange(len(df_fil)) / fs

    fig, axs = plt.subplots(2, 2, figsize=(12, 6), sharex="col")
    fig.suptitle(raw_path.name, fontsize=12, fontweight="bold")
    axs[0, 0].plot(t_raw, df_raw["I"]); axs[0, 0].set_title("Raw I"); axs[0, 0].set_ylabel("Amplitude")
    axs[1, 0].plot(t_raw, df_raw["Q"]); axs[1, 0].set_title("Raw Q"); axs[1, 0].set_xlabel("Time (s)"); axs[1, 0].set_ylabel("Amplitude")
    axs[0, 1].plot(t_fil, df_fil["I"]); axs[0, 1].set_title("Filtered I")
    axs[1, 1].plot(t_fil, df_fil["Q"]); axs[1, 1].set_title("Filtered Q"); axs[1, 1].set_xlabel("Time (s)")
    for ax in axs.flat:
        ax.grid(True, alpha=0.3)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()


def plot_iq_circle(i_all, q_all, radius=None, plot_fit=True, plot_limit_scale=1.0):
    """Plot I vs Q trajectory with fitted circle overlay."""
    Ic = np.array(i_all)
    Qc = np.array(q_all)

    if radius is None:
        radius = np.max(np.sqrt(Ic**2 + Qc**2))
    r_v = radius

    plt.figure(figsize=(6, 6))
    plt.plot(Ic, Qc, color='blue', alpha=0.8, label='Recorded I vs Q')

    if plot_fit:
        circle = plt.Circle((0, 0), radius, color='red', linestyle='--',
                            linewidth=2, alpha=0.8, fill=False, label='Ideal Circle')
        plt.gca().add_artist(circle)
        max_Ic, min_Ic = Ic.max(), Ic.min()
        max_Qc, min_Qc = Qc.max(), Qc.min()
        limit = max(radius, max(max_Ic - min_Ic, max_Qc - min_Qc) / 2) + 0.1 * radius
        x_min, x_max = -limit * 1.3, limit * 1.3
        y_min, y_max = -limit * 1.3, limit * 1.3
    else:
        max_Ic, min_Ic = Ic.max(), Ic.min()
        max_Qc, min_Qc = Qc.max(), Qc.min()
        limit = max(max_Ic - min_Ic, max_Qc - min_Qc) / 2
        x_min, x_max = -limit * plot_limit_scale, limit * plot_limit_scale
        y_min, y_max = -limit * plot_limit_scale, limit * plot_limit_scale

    plt.xlim(x_min, x_max); plt.ylim(y_min, y_max)
    plt.gca().set_aspect('equal', adjustable='box')
    plt.xlabel('I Amplitude (V)'); plt.ylabel('Q Amplitude (V)')
    plt.grid(True); plt.title("I vs Q Plot with Ideal Circle", fontsize=12)
    plt.legend(loc='upper right')
    plt.text(0.325, 0.95, f'Radius: {r_v:.6f} V',
             transform=plt.gca().transAxes, fontsize=10,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(facecolor='white', edgecolor='black', boxstyle='round,pad=0.3'))
    plt.tight_layout()
    plt.show()


# ==========================================================
# 5) RCS Helper Functions
# ==========================================================

def wavelength_from_freq(freq_hz: float) -> float:
    return 3e8 / float(freq_hz)


def rcs_square_plate_po(freq_hz: float, width_cm: float, length_cm: float | None = None) -> float:
    """
    Physical Optics RCS at normal incidence:
      σ = 4π * A^2 / λ^2, A = (width * length)
    """
    lam = wavelength_from_freq(freq_hz)
    width_m = float(width_cm) / 100.0
    length_m = (float(length_cm) / 100.0) if length_cm is not None else width_m
    A = width_m * length_m
    return 4.0 * np.pi * (A**2) / (lam**2)


def rcs_from_amplitude_ratio(sigma_cal_m2, A_meas, A_cal, power_exponent=2):
    """σ_human = σ_cal * (A_meas/A_cal)^k. Default k=2."""
    ratio = (A_meas + 1e-20) / (A_cal + 1e-20)
    return float(sigma_cal_m2 * (ratio ** power_exponent))


# ==========================================================
# 6) Core BioRadar Processing (for batch / non-plotting use)
# ==========================================================

def correct_fit_center_demod(I, Q, A_e, phi_e, lam_m):
    """
    Apply imbalance correction -> LM circle fit -> center -> demod -> unwrap.
    Returns dict with corrected/centered I/Q, circle params, and displacement.
    """
    I_corr, Q_corr = br.imbalance_corrector(I, Q, A_e, phi_e)
    xc, yc, R = br.Leven_Marq3(I_corr, Q_corr)
    I_cent, Q_cent = br.circle_shifter(I_corr, Q_corr, -float(xc), -float(yc))
    theta = br.demod_theta(I_cent, Q_cent)
    theta_unw = np.asarray(br.unwrap_angles(theta), dtype=float)
    disp_m = (float(lam_m) / (4.0 * np.pi)) * theta_unw

    return {
        "I_corr": np.asarray(I_corr, float), "Q_corr": np.asarray(Q_corr, float),
        "I_cent": np.asarray(I_cent, float), "Q_cent": np.asarray(Q_cent, float),
        "xc": float(xc), "yc": float(yc), "R": float(R),
        "disp_m": np.asarray(disp_m, float),
    }


# ==========================================================
# 7) Output Saving Helpers
# ==========================================================

def _tag(freq_hz, dist_m):
    ftag = f"{freq_hz/1e9:g}GHz".replace(".", "p")
    dtag = f"{dist_m:g}m".replace(".", "p")
    return f"{ftag}_{dtag}"


def save_bucket(freq_hz, dist_m, df_out=None, subdir="results"):
    """Save a summary CSV into OUT_DIR/subdir."""
    if "OUT_DIR" not in globals():
        raise ValueError("OUT_DIR not defined in notebook")

    tag = _tag(freq_hz, dist_m)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    if df_out is not None and isinstance(df_out, pd.DataFrame) and len(df_out):
        out_path = out_dir / f"{tag}_{ts}.csv"
        df_out.to_csv(out_path, index=False)
        print(f"✓ saved → {out_path}")
        return out_path

    print("Nothing to save (df_out empty or None).")
    return None


# ==========================================================
# 8) Quick Analysis (interactive trim + inspect)
# ==========================================================

def quick_analysis(
    idata, qdata, gain=1.0,
    start_sample=None, end_sample=None,
    gen_coeffs=False, Ae=None, Pe=None,
    use_filter=False, fc=1.0, filt_order=6, fs=1000.0,
    freq_rf=2.4e9,
    A_cal=None, sigma_cal=None,
    plot_fit=True, plot_limit_scale=1.3,
    gen_plots=True,
):
    """
    Quick I/Q sanity check pipeline with optional filtering and trim window.

    Parameters
    ----------
    start_sample, end_sample : int or None
        Absolute sample indices defining the trim window. None means
        "use full start" / "use full end". Example: start_sample=2000,
        end_sample=58000 keeps samples 2000..58000 of the full record.

    gen_plots : bool, default=True
        If True, generate all diagnostic plots.
        If False, process normally but skip plotting.

    Returns
    -------
    pd.DataFrame
        Single-row DataFrame with columns:
          ae, pe, xc, yc, r, sigma_human, peak_to_peak_cm,
          start_sample, end_sample, N_samples_used, disp_cm
    """
    f_max = 1.0
    f_sig = 0.2
    f_ylim_min = 0.05

    idata = np.asarray(idata) / gain
    qdata = np.asarray(qdata) / gain

    # Build slice from absolute indices
    seg = slice(start_sample, end_sample)

    # 0) Optional low-pass
    if use_filter:
        i_use = lowpass_python_safe(idata, fc=fc, fs=fs, order=filt_order)
        q_use = lowpass_python_safe(qdata, fc=fc, fs=fs, order=filt_order)
        raw_title_suffix = f" (Low-pass fc={fc} Hz)"
        filt_mode_str = f"LOW-PASS ENABLED (fc={fc} Hz, order={filt_order})"
    else:
        i_use, q_use = idata, qdata
        raw_title_suffix = ""
        filt_mode_str = "NO LOW-PASS FILTER"

    # 1) Plot raw/filtered I/Q
    if gen_plots:
        fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        axs[0].plot(i_use, label="I", color="blue")
        axs[0].set_title("I Channel" + raw_title_suffix)
        axs[0].set_ylabel("Voltage (V)")
        axs[0].grid(True)
        axs[0].legend()

        axs[1].plot(q_use, label="Q", color="orange")
        axs[1].set_title("Q Channel" + raw_title_suffix)
        axs[1].set_xlabel("Sample Index")
        axs[1].set_ylabel("Voltage (V)")
        axs[1].grid(True)
        axs[1].legend()

        for ax in axs:
            if start_sample is not None:
                ax.axvline(start_sample, color="gray", linestyle="--", alpha=0.6)
            if end_sample is not None:
                ax.axvline(end_sample, color="gray", linestyle="--", alpha=0.6)

        plt.suptitle("Raw I and Q Time-Domain Signals", fontsize=14)
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        plt.show()

    # 2) Imbalance coefficients with safe fallback
    fallback_ae = 1.0
    fallback_pe = 0.0

    try:
        if gen_coeffs:
            ae, pe = br.get_imbalance_values(i_use, q_use)
            coeff_mode = "generated (forced)"
        else:
            if (Ae is not None) and (Pe is not None):
                ae, pe = Ae, Pe
                coeff_mode = "passed in"
            else:
                ae, pe = br.get_imbalance_values(i_use, q_use)
                coeff_mode = "generated"
    except Exception as e:
        ae, pe = fallback_ae, fallback_pe
        coeff_mode = "failed (auto)"
        print(f"[WARN] Failed to generate imbalance coefficients: {e}")
        print(f"[WARN] Falling back to default coefficients: Ae={ae}, Pe={pe}")

    # 3) Correct imbalance
    Ip, Qp = br.imbalance_corrector(i_use, q_use, ae, pe)

    # 4) Circle fit & centering
    xc, yc, r = br.Leven_Marq3(Ip[seg], Qp[seg])
    Ip_centered = Ip - xc
    Qp_centered = Qp - yc

    # 5) Plot corrected I/Q
    if gen_plots:
        fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        axs[0].plot(Ip_centered[seg], label="I (corrected)", color="blue")
        axs[0].set_title("I Channel (Corrected & Centered)")
        axs[0].set_ylabel("Voltage (V)")
        axs[0].grid(True)
        axs[0].legend()

        axs[1].plot(Qp_centered[seg], label="Q (corrected)", color="orange")
        axs[1].set_title("Q Channel (Corrected & Centered)")
        axs[1].set_xlabel("Sample Index")
        axs[1].set_ylabel("Voltage (V)")
        axs[1].grid(True)
        axs[1].legend()

        plt.suptitle("Corrected I and Q Time-Domain Signals", fontsize=14)
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        plt.show()

        # 6) IQ Circle
        plot_iq_circle(Ip_centered[seg], Qp_centered[seg], r, plot_fit, plot_limit_scale)

    # 7) Displacement + FFT
    theta = br.demod_theta(Ip_centered[seg], Qp_centered[seg])
    theta_unw = br.unwrap_angles(theta)
    wavelength_m = wavelength_from_freq(freq_rf)
    disp_m = (wavelength_m / (4.0 * np.pi)) * np.asarray(theta_unw)
    disp_cm = disp_m * 100.0

    N = len(disp_cm)
    disp_pp = float(disp_cm.max() - disp_cm.min()) if N > 1 else np.nan

    if N > 1:
        t = np.arange(N) / fs
        win = np.hanning(N)
        sig_win = disp_cm.astype(float) * win
        freqs = np.fft.rfftfreq(N, d=1.0 / fs)
        mag = np.abs(np.fft.rfft(sig_win)) / np.sum(win)
        mask = (freqs >= 0) & (freqs <= f_max)
        freqs_plot = freqs[mask]
        mag_plot = mag[mask]

        max_fft_for_ylim = None
        if freqs_plot.size > 0:
            mask_ylim = freqs_plot >= f_ylim_min
            if mask_ylim.any():
                max_fft_for_ylim = float(mag_plot[mask_ylim].max())

        if gen_plots:
            fig, (ax_t, ax_f) = plt.subplots(2, 1, figsize=(10, 6), sharex=False)
            fig.suptitle("Displacement & FFT (from corrected I/Q)", fontsize=14)

            ax_t.plot(t, disp_cm, linewidth=1.1)
            ax_t.set_xlabel("Time (s)")
            ax_t.set_ylabel("Displacement (cm)")
            ax_t.grid(True, alpha=0.35)
            ax_t.text(
                0.02, 0.95, f"Peak-to-peak: {disp_pp:.3f} cm",
                transform=ax_t.transAxes, fontsize=10,
                verticalalignment="top",
                bbox=dict(facecolor="white", edgecolor="black", boxstyle="round,pad=0.3")
            )

            if freqs_plot.size > 0:
                ax_f.plot(freqs_plot, mag_plot, linewidth=1.1)
                ax_f.axvline(f_sig, linestyle="--", alpha=0.6, label=f"{f_sig:.2f} Hz")
                ax_f.legend()

            ax_f.set_xlabel("Frequency (Hz)")
            ax_f.set_ylabel("|FFT(disp)| (arb.)")
            ax_f.grid(True, alpha=0.35)

            if max_fft_for_ylim is not None:
                ax_f.set_ylim(0, max_fft_for_ylim * 1.05)

            plt.tight_layout(rect=[0, 0, 1, 0.93])
            plt.show()
    else:
        if gen_plots:
            print("[INFO] Not enough samples for FFT plot (N <= 1).")

    # 8) Compute σ_human
    sigma_human = np.nan
    if A_cal is not None and sigma_cal is not None:
        sigma_human = rcs_from_amplitude_ratio(sigma_cal, r, A_cal, power_exponent=2)

    # 9) Summary
    LBL = 28
    BAR = 64
    print("\n" + "=" * BAR)
    print("QUICK ANALYSIS SUMMARY".center(BAR))
    print("=" * BAR)
    print(f"{'Filter mode':<{LBL}}: {filt_mode_str}")
    print(f"{'Ae (Amplitude Imbalance)':<{LBL}}: {ae:.6f}  [{coeff_mode}]")
    print(f"{'Pe (Phase Imbalance, rad)':<{LBL}}: {pe:.6f}  [{coeff_mode}]")
    print(f"{'xc (Circle Center X)':<{LBL}}: {xc:.6f}")
    print(f"{'yc (Circle Center Y)':<{LBL}}: {yc:.6f}")
    print(f"{'Ar (Circle Radius)':<{LBL}}: {r:.6f}")
    print(f"{'p2p displacement':<{LBL}}: {disp_pp:.4f} cm")
    if not np.isnan(sigma_human):
        print(f"{'ERCS (m²)':<{LBL}}: {sigma_human:.6f} m²")
        print(f"{'ERCS (dBsm)':<{LBL}}: {10*np.log10(sigma_human):.6f} dBsm")
    print("=" * BAR + "\n")

    # 10) Return results
    return pd.DataFrame([{
        "ae": ae,
        "pe": pe,
        "coeff_mode": coeff_mode,
        "xc": xc,
        "yc": yc,
        "r": r,
        "sigma_human": sigma_human,
        "peak_to_peak_cm": disp_pp,
        "start_sample": start_sample,
        "end_sample": end_sample,
        "N_samples_used": N,
        "disp_cm": disp_cm,
    }])

# ==========================================================
# 9) Measurement Loading Helpers
# ==========================================================

def lookup_file_row(df_files, subject, dist_m, freq_hz, pol_tx, dset):
    """
    Find the single df_files row matching the given measurement specifier.
    Raises if zero matches, warns if multiple (returns the first).
    """
    df_sub = get_subset(df_files, subject=subject, dist_m=dist_m,
                        freq_hz=freq_hz, pol_tx=pol_tx, dset=dset)
    if len(df_sub) == 0:
        raise ValueError(
            f"No file found for {subject} / {dist_m} m / "
            f"{freq_hz/1e9:g} GHz / {pol_tx}tx / dset={dset}"
        )
    if len(df_sub) > 1:
        print(f"[WARN] {len(df_sub)} files match — using first.")
        display(df_sub[["filename", "gain", "dset"]])
    return df_sub.iloc[0]


def load_calibration(freq_hz, dist_m, pol_tx, cal_plate_cm, cal_version="new"):
    """
    Pull Ae, Pe, A_cal, sigma_cal for the specified frontend/freq/dist/pol/plate.
    Frontend is inferred from freq_hz (2.4 GHz → apa_circ, 24 GHz → klc7).
    Returns dict: {frontend, Ae, Pe, A_cal, sigma_cal}.
    """
    frontend = "apa_circ" if freq_hz == 2.4e9 else "klc7"
    Ae, Pe = get_imbalance_coeffs(frontend, freq_hz, dist_m,
                                  plate_cm=cal_plate_cm,
                                  pol=pol_tx, version=cal_version)
    A_cal     = get_R_cal(frontend, freq_hz, dist_m,
                          plate_cm=cal_plate_cm,
                          pol=pol_tx, version=cal_version)
    sigma_cal = get_sigma_cal(frontend, freq_hz, plate_cm=cal_plate_cm)
    return {
        "frontend":  frontend,
        "Ae":        Ae,
        "Pe":        Pe,
        "A_cal":     A_cal,
        "sigma_cal": sigma_cal,
    }


def load_iq(row):
    """
    Read I/Q CSV from a df_files row. Returns (df_iq, N_samples).
    """
    df_iq = read_iq_csv(row.filepath)
    return df_iq, len(df_iq)

def print_measurement_summary(row, cal, N, start_sample, end_sample,
                              cal_plate_cm, pol_tx, cal_version, fs=1000.0):
    """
    Print a header summary for a measurement being analyzed:
      file info, sample count, gain, calibration values, and trim window.
    """
    t_start_s = (start_sample or 0) / fs
    t_end_s   = (end_sample if end_sample is not None else N) / fs

    print(f"File   : {row.filename}")
    print(f"Samples: {N} ({N/fs:.1f} s)")
    print(f"Gain   : {row.gain}")
    print(f"Cal    : {cal_plate_cm} cm / pol={pol_tx} / version={cal_version}")
    print(f"         Ae={cal['Ae']:.6f}, Pe={cal['Pe']:.6f}, "
          f"A_cal={cal['A_cal']:.6f}, σ_cal={cal['sigma_cal']:.4f} m²")
    print(f"Trim   : [{start_sample}, {end_sample}] samples "
          f"→ [{t_start_s:.1f}, {t_end_s:.1f}] s "
          f"(duration {t_end_s - t_start_s:.1f} s)")
    print("-" * 60)


# ==========================================================
# 10) Results Persistence
# ==========================================================

RESULTS_FILE = None  # lazy-resolved


def _results_path():
    """Lazy-resolve OUT_DIR so this module doesn't require it at import."""
    global RESULTS_FILE
    if RESULTS_FILE is None:
        if "OUT_DIR" not in globals():
            raise ValueError("OUT_DIR not defined in notebook")
        RESULTS_FILE = OUT_DIR / "results.json"
        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    return RESULTS_FILE


def load_results():
    """Load all saved records as a list. Returns [] if file doesn't exist."""
    path = _results_path()
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return []


def _write_results(results):
    """Pretty-printed write for readability / git diffs."""
    with open(_results_path(), "w") as f:
        json.dump(results, f, indent=2)


def _matches_file(rec, subject, dist_m, freq_hz, pol_tx, dset,
                  cal_plate_cm, cal_version, segment_type=None):
    """Does a record refer to the same measurement + cal (+ optionally type)?"""
    same = (
        rec["subject"]      == subject
        and rec["dist_m"]   == float(dist_m)
        and rec["freq_hz"]  == float(freq_hz)
        and rec["pol_tx"]   == pol_tx
        and rec["dset"]     == int(dset)
        and rec["cal_plate_cm"] == int(cal_plate_cm)
        and rec["cal_version"]  == cal_version
    )
    if segment_type is not None:
        same = same and rec.get("segment_type") == segment_type
    return same


def _next_segment_id(results, subject, dist_m, freq_hz, pol_tx, dset,
                     cal_plate_cm, cal_version, segment_type):
    """Next unused integer segment ID, scoped per (file+cal+segment_type)."""
    used = [
        rec["segment"] for rec in results
        if _matches_file(rec, subject, dist_m, freq_hz, pol_tx, dset,
                         cal_plate_cm, cal_version, segment_type=segment_type)
    ]
    if not used:
        return 0
    return max(used) + 1


def save_result(df_result, subject, dist_m, freq_hz, pol_tx, dset,
                cal_plate_cm, cal_version,
                use_filter, fc, filt_order, fs,
                segment_type, segment=None, notes=""):
    """
    Persist a single trimmed segment's results.

    segment_type: "single" or "multi"
    segment:
        None -> auto-assign next unused integer for this file+cal+type
        int  -> overwrite that specific segment (or create if not present)
    """
    if segment_type not in ("single", "multi"):
        raise ValueError(f"segment_type must be 'single' or 'multi', got {segment_type!r}")

    row = df_result.iloc[0]
    results = load_results()

    if segment is None:
        segment = _next_segment_id(results, subject, dist_m, freq_hz,
                                   pol_tx, dset, cal_plate_cm, cal_version,
                                   segment_type)
        action = "saved (new)"
    else:
        segment = int(segment)
        action = "saved (new)"
        for i, rec in enumerate(results):
            if (_matches_file(rec, subject, dist_m, freq_hz, pol_tx, dset,
                              cal_plate_cm, cal_version,
                              segment_type=segment_type)
                    and rec["segment"] == segment):
                results.pop(i)
                action = "overwrote"
                break

    record = {
        # --- identifiers ---
        "subject":      subject,
        "dist_m":       float(dist_m),
        "freq_hz":      float(freq_hz),
        "pol_tx":       pol_tx,
        "dset":         int(dset),
        "segment_type": segment_type,
        "segment":      int(segment),

        # --- calibration used ---
        "cal_plate_cm": int(cal_plate_cm),
        "cal_version":  cal_version,

        # --- processing settings ---
        "use_filter":   bool(use_filter),
        "fc":           float(fc),
        "filt_order":   int(filt_order),
        "fs":           float(fs),

        # --- trim window ---
        "start_sample":   None if pd.isna(row["start_sample"]) else int(row["start_sample"]),
        "end_sample":     None if pd.isna(row["end_sample"])   else int(row["end_sample"]),
        "N_samples_used": int(row["N_samples_used"]),

        # --- scalar results ---
        "ae":              float(row["ae"]),
        "pe":              float(row["pe"]),
        "xc":              float(row["xc"]),
        "yc":              float(row["yc"]),
        "r":               float(row["r"]),
        "sigma_human":     float(row["sigma_human"]) if not pd.isna(row["sigma_human"]) else None,
        "peak_to_peak_cm": float(row["peak_to_peak_cm"]) if not pd.isna(row["peak_to_peak_cm"]) else None,

        # --- metadata ---
        "notes":    notes,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }

    results.append(record)
    _write_results(results)

    print(f"✓ {action} {segment_type}-segment {segment} for "
          f"{subject} / {dist_m} m / {freq_hz/1e9:g} GHz / {pol_tx}tx / "
          f"dset={dset} / {cal_plate_cm}cm_{cal_version}")


def get_saved_segments(subject=None, dist_m=None, freq_hz=None,
                       pol_tx=None, dset=None,
                       cal_plate_cm=None, cal_version=None,
                       segment_type=None):
    """
    Return matching records as a DataFrame. Any arg as None = don't filter on it.
    """
    results = load_results()
    filters = {
        "subject": subject, "dist_m": dist_m, "freq_hz": freq_hz,
        "pol_tx": pol_tx, "dset": dset,
        "cal_plate_cm": cal_plate_cm, "cal_version": cal_version,
        "segment_type": segment_type,
    }
    def keep(rec):
        for k, v in filters.items():
            if v is None:
                continue
            if k in ("dist_m", "freq_hz"):
                if rec.get(k) != float(v):
                    return False
            elif k in ("dset", "cal_plate_cm"):
                if rec.get(k) != int(v):
                    return False
            else:
                if rec.get(k) != v:
                    return False
        return True
    return pd.DataFrame([r for r in results if keep(r)])


def load_segment(subject, dist_m, freq_hz, pol_tx, dset,
                 cal_plate_cm, cal_version, segment_type, segment):
    """
    Return the full saved record for one specific segment.
    """
    df = get_saved_segments(subject, dist_m, freq_hz, pol_tx, dset,
                            cal_plate_cm, cal_version,
                            segment_type=segment_type)
    df = df[df["segment"] == int(segment)]
    if len(df) == 0:
        raise KeyError(
            f"No saved {segment_type}-segment {segment} for "
            f"{subject} / {dist_m} m / {freq_hz/1e9:g} GHz / {pol_tx}tx / "
            f"dset={dset} / {cal_plate_cm}cm_{cal_version}"
        )
    return df.iloc[0].to_dict()

def plot_subject_rcs_from_df(
    df,
    freq_hz,
    segment_type="single",
    subjects=None,
    polarization=None,
    plot_dbsm=False,
    title=None,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    figsize=(9, 5),
    jitter=0.015,
):
    """
    Plot RCS vs distance for one frequency from a saved-results DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing saved segment results.
    freq_hz : float
        Frequency to plot, e.g. 2.4e9 or 24e9.
    segment_type : str
        'single' or 'multi'
    subjects : list[str] or None
        If None, plot all subjects. Otherwise plot only these subjects.
    polarization : str or None
        If None, plot all polarizations.
        Accepts 'V', 'H', 'vertical', or 'horizontal'.
    plot_dbsm : bool
        If True, plot sigma in dBsm. Otherwise plot in m^2.
    title : str or None
        Custom title. If None, a default title is created.
    """

    df_plot = df[
        (df[freq_col] == freq_hz) &
        (df[segtype_col].str.lower() == segment_type.lower())
    ].copy()

    if subjects is not None:
        df_plot = df_plot[df_plot[subject_col].isin(subjects)].copy()

    # --- polarization filter ---
    if polarization is not None:
        pol_map = {
            "v": "V",
            "vertical": "V",
            "h": "H",
            "horizontal": "H",
        }

        pol_key = str(polarization).strip().lower()
        if pol_key not in pol_map:
            raise ValueError("polarization must be one of: None, 'V', 'H', 'vertical', 'horizontal'")

        pol_val = pol_map[pol_key]
        df_plot = df_plot[df_plot[pol_col].astype(str).str.upper() == pol_val].copy()

    if df_plot.empty:
        print(
            f"No data found for freq_hz={freq_hz}, "
            f"segment_type='{segment_type}', polarization={polarization}."
        )
        return

    # Handle units
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    freq_ghz = freq_hz / 1e9

    if title is None:
        subj_str = "All Subjects" if subjects is None else ", ".join(subjects)

        if polarization is None:
            pol_str = "All Polarizations"
        else:
            pol_str = "Vertical" if pol_val == "V" else "Horizontal"

        title = (
            f"{subj_str} — {freq_ghz:g} GHz, "
            f"{segment_type.capitalize()} Segments, {pol_str}, {unit_str}"
        )

    fig, ax = plt.subplots(figsize=figsize)

    unique_subjects = sorted(df_plot[subject_col].dropna().unique())
    cmap = plt.get_cmap("tab10")

    for idx, subj in enumerate(unique_subjects):
        df_subj = df_plot[df_plot[subject_col] == subj].copy()
        color = cmap(idx % 10)

        grouped = df_subj.groupby(dist_col)
        first_dist = True

        for dist in sorted(grouped.groups.keys()):
            df_dist = grouped.get_group(dist)

            y = df_dist["sigma_plot"].dropna().to_numpy()
            if len(y) == 0:
                continue

            x = np.full(len(y), dist, dtype=float)

            # small jitter so repeated points do not overlap exactly
            xj = x + (np.arange(len(y)) - (len(y) - 1) / 2.0) * jitter

            ax.scatter(
                xj, y,
                s=45,
                alpha=0.85,
                color=color,
                label=subj if first_dist else None,
            )
            first_dist = False

    dists = sorted(df_plot[dist_col].dropna().unique())
    if len(dists) > 0:
        ax.set_xlim(min(dists) - 0.2, max(dists) + 0.2)
        ax.set_xticks(dists)

    ax.set_xlabel("Distance (m)")
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(title="Subject", fontsize=9, title_fontsize=10)

    plt.tight_layout()
    plt.show()


import numpy as np
import matplotlib.pyplot as plt

def plot_subject_rcs_profile_2x2(
    df_all,
    subject,
    freq_hz,
    plot_dbsm=False,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    figsize=(12, 8),
    jitter=0.015,
):
    """
    Plot a 2x2 RCS profile figure for one subject at one frequency.

    Layout
    ------
    Top-left     : multi-segment, vertical polarization
    Top-right    : multi-segment, horizontal polarization
    Bottom-left  : single-segment, vertical polarization
    Bottom-right : single-segment, horizontal polarization

    Parameters
    ----------
    df_all : pd.DataFrame
        DataFrame containing saved segment results.
    subject : str
        Subject name to plot.
    freq_hz : float
        Frequency to plot, e.g. 2.4e9 or 24e9.
    plot_dbsm : bool, default=False
        If True, plot sigma in dBsm. Otherwise plot in m^2.
    """

    # -----------------------------
    # Filter to subject + frequency
    # -----------------------------
    df_plot = df_all[
        (df_all[subject_col] == subject) &
        (df_all[freq_col] == freq_hz)
    ].copy()

    if df_plot.empty:
        print(f"No data found for subject='{subject}' at freq_hz={freq_hz}.")
        return

    # -----------------------------
    # Normalize polarization labels
    # -----------------------------
    pol_map = {
        "v": "V",
        "vertical": "V",
        "vert": "V",
        "h": "H",
        "horizontal": "H",
        "horz": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_plot[pol_col] = df_plot[pol_col].apply(normalize_pol)
    df_plot[segtype_col] = df_plot[segtype_col].astype(str).str.lower()

    # -----------------------------
    # Handle units
    # -----------------------------
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    freq_ghz = freq_hz / 1e9

    # -----------------------------
    # Make figure
    # -----------------------------
    fig, axs = plt.subplots(2, 2, figsize=figsize, sharex=True, sharey=True)

    panel_specs = [
        ("multi",  "V", axs[0, 0], "Multi-Segment, Vertical"),
        ("multi",  "H", axs[0, 1], "Multi-Segment, Horizontal"),
        ("single", "V", axs[1, 0], "Single-Segment, Vertical"),
        ("single", "H", axs[1, 1], "Single-Segment, Horizontal"),
    ]

    all_dists = sorted(df_plot[dist_col].dropna().unique())

    for seg_type, pol, ax, panel_title in panel_specs:
        df_panel = df_plot[
            (df_plot[segtype_col] == seg_type) &
            (df_plot[pol_col] == pol)
        ].copy()

        if df_panel.empty:
            ax.set_title(panel_title)
            ax.text(
                0.5, 0.5, "No data",
                transform=ax.transAxes,
                ha="center", va="center",
                fontsize=11
            )
            ax.grid(True, linestyle="--", alpha=0.4)
            continue

        grouped = df_panel.groupby(dist_col)

        for dist in sorted(grouped.groups.keys()):
            df_dist = grouped.get_group(dist)

            y = df_dist["sigma_plot"].dropna().to_numpy()
            if len(y) == 0:
                continue

            x = np.full(len(y), dist, dtype=float)
            xj = x + (np.arange(len(y)) - (len(y) - 1) / 2.0) * jitter

            ax.scatter(
                xj, y,
                s=45,
                alpha=0.85,
            )

        ax.set_title(panel_title)
        ax.grid(True, linestyle="--", alpha=0.4)

    # -----------------------------
    # Axis formatting
    # -----------------------------
    if len(all_dists) > 0:
        x_min = min(all_dists) - 0.2
        x_max = max(all_dists) + 0.2
        for ax in axs.flat:
            ax.set_xlim(x_min, x_max)
            ax.set_xticks(all_dists)

    axs[1, 0].set_xlabel("Distance (m)")
    axs[1, 1].set_xlabel("Distance (m)")
    axs[0, 0].set_ylabel(y_label)
    axs[1, 0].set_ylabel(y_label)

    fig.suptitle(
        f"{subject} — {freq_ghz:g} GHz RCS Profile ({unit_str})",
        fontsize=14
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()

import numpy as np
import pandas as pd

def compute_pol_difference_table(
    df,
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    sigma_col="sigma_human",
):
    """
    Create a simple table with sigma_V, sigma_H, sigma_V_dBsm, sigma_H_dBsm,
    and delta_V_minus_H_dB = sigma_V_dBsm - sigma_H_dBsm.

    Pairing is done by:
      subject, dist_m, freq_hz, segment_type

    If multiple rows exist within one polarization for the same condition,
    they are averaged first.
    """

    df_use = df.copy()

    # normalize polarization labels
    pol_map = {
        "v": "V",
        "vertical": "V",
        "vert": "V",
        "h": "H",
        "horizontal": "H",
        "horz": "H",
    }

    df_use[pol_col] = (
        df_use[pol_col]
        .astype(str)
        .str.strip()
        .str.lower()
        .map(pol_map)
    )

    df_use = df_use[df_use[pol_col].isin(["V", "H"])].copy()

    # average repeated rows within each polarization
    df_avg = (
        df_use.groupby([subject_col, dist_col, freq_col, segtype_col, pol_col], as_index=False)[sigma_col]
        .mean()
    )

    # pivot V and H into columns
    df_wide = df_avg.pivot(
        index=[subject_col, dist_col, freq_col, segtype_col],
        columns=pol_col,
        values=sigma_col
    ).reset_index()

    df_wide.columns.name = None
    df_wide = df_wide.rename(columns={"V": "sigma_V", "H": "sigma_H"})

    # dBsm columns
    df_wide["sigma_V_dBsm"] = np.where(df_wide["sigma_V"] > 0, 10*np.log10(df_wide["sigma_V"]), np.nan)
    df_wide["sigma_H_dBsm"] = np.where(df_wide["sigma_H"] > 0, 10*np.log10(df_wide["sigma_H"]), np.nan)

    # difference in dB
    df_wide["delta_V_minus_H_dB"] = df_wide["sigma_V_dBsm"] - df_wide["sigma_H_dBsm"]

    # optional linear ratio too
    df_wide["V_over_H_linear"] = np.where(
        (df_wide["sigma_V"] > 0) & (df_wide["sigma_H"] > 0),
        df_wide["sigma_V"] / df_wide["sigma_H"],
        np.nan
    )

    return df_wide.sort_values([subject_col, freq_col, segtype_col, dist_col]).reset_index(drop=True)

def summarize_polarization_preference(
    df_ratio,
    subject_col="subject",
    freq_col="freq_hz",
    segtype_col="segment_type",
):
    """
    Summarize V-vs-H preference from the paired ratio table.
    """

    def frac_positive(x):
        x = x.dropna()
        return np.nan if len(x) == 0 else np.mean(x > 0)

    summary = (
        df_ratio.groupby([subject_col, freq_col, segtype_col], dropna=False)
        .agg(
            n_pairs=("V_minus_H_dB", lambda x: x.notna().sum()),
            mean_V_minus_H_dB=("V_minus_H_dB", "mean"),
            std_V_minus_H_dB=("V_minus_H_dB", "std"),
            median_V_minus_H_dB=("V_minus_H_dB", "median"),
            mean_V_over_H_linear=("V_over_H_linear", "mean"),
            frac_V_stronger=("V_minus_H_dB", frac_positive),
        )
        .reset_index()
    )

    return summary

import matplotlib.pyplot as plt

def plot_polarization_preference_heatmap(
    df_ratio,
    freq_hz,
    segment_type="single",
    value_col="V_minus_H_dB",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    figsize=(8, 5),
    cmap="coolwarm",
):
    """
    Heatmap of polarization preference across subjects and distances.

    value_col:
      - 'V_minus_H_dB' is recommended
      - or 'V_over_H_linear'
    """

    df_plot = df_ratio[
        (df_ratio[freq_col] == freq_hz) &
        (df_ratio[segtype_col].str.lower() == segment_type.lower())
    ].copy()

    if df_plot.empty:
        print(f"No paired data found for freq_hz={freq_hz} and segment_type='{segment_type}'.")
        return

    # average if multiple matched rows exist for same subject/distance
    heat_df = (
        df_plot.groupby([subject_col, dist_col], as_index=False)[value_col]
        .mean()
        .pivot(index=subject_col, columns=dist_col, values=value_col)
    )

    if heat_df.empty:
        print("No data available for heatmap.")
        return

    fig, ax = plt.subplots(figsize=figsize)

    vals = heat_df.to_numpy(dtype=float)

    if value_col == "V_minus_H_dB":
        vmax = np.nanmax(np.abs(vals))
        vmin = -vmax
        im = ax.imshow(vals, aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
        cbar_label = "V - H (dB)"
    else:
        im = ax.imshow(vals, aspect="auto", cmap=cmap)
        cbar_label = value_col

    ax.set_xticks(np.arange(len(heat_df.columns)))
    ax.set_xticklabels(heat_df.columns)
    ax.set_yticks(np.arange(len(heat_df.index)))
    ax.set_yticklabels(heat_df.index)

    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Subject")

    freq_ghz = freq_hz / 1e9
    ax.set_title(f"Polarization Preference Heatmap — {freq_ghz:g} GHz, {segment_type.capitalize()}")

    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label(cbar_label)

    plt.tight_layout()
    plt.show()


def compute_polarization_ratio_table(
    df,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    extra_match_cols=None,
):
    """
    Build a paired V/H comparison table from a results DataFrame.

    Output columns include:
      sigma_V
      sigma_H
      V_over_H_linear
      V_minus_H_dB
    """

    df_use = df.copy()

    # Normalize polarization labels
    pol_map = {
        "v": "V",
        "vertical": "V",
        "vert": "V",
        "h": "H",
        "horizontal": "H",
        "horz": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_use[pol_col] = df_use[pol_col].apply(normalize_pol)

    if extra_match_cols is None:
        extra_match_cols = []

    match_cols = [subject_col, dist_col, freq_col, segtype_col] + extra_match_cols

    # Keep only V/H rows
    df_use = df_use[df_use[pol_col].isin(["V", "H"])].copy()

    # Pivot so V and H become columns
    pivot = (
        df_use.pivot_table(
            index=match_cols,
            columns=pol_col,
            values=sigma_col,
            aggfunc="mean",
        )
        .reset_index()
    )

    pivot.columns.name = None

    if "V" not in pivot.columns:
        pivot["V"] = np.nan
    if "H" not in pivot.columns:
        pivot["H"] = np.nan

    out = pivot.rename(columns={"V": "sigma_V", "H": "sigma_H"}).copy()

    # Compute ratios/differences
    valid_linear = (out["sigma_V"] > 0) & (out["sigma_H"] > 0)

    out["V_over_H_linear"] = np.nan
    out.loc[valid_linear, "V_over_H_linear"] = (
        out.loc[valid_linear, "sigma_V"] / out.loc[valid_linear, "sigma_H"]
    )

    out["V_minus_H_dB"] = np.nan
    out.loc[valid_linear, "V_minus_H_dB"] = 10 * np.log10(out.loc[valid_linear, "V_over_H_linear"])

    out["sigma_V_dBsm"] = np.nan
    out["sigma_H_dBsm"] = np.nan
    out.loc[out["sigma_V"] > 0, "sigma_V_dBsm"] = 10 * np.log10(
        out.loc[out["sigma_V"] > 0, "sigma_V"]
    )
    out.loc[out["sigma_H"] > 0, "sigma_H_dBsm"] = 10 * np.log10(
        out.loc[out["sigma_H"] > 0, "sigma_H"]
    )

    # Helpful indicator
    out["preferred_pol"] = pd.Series(index=out.index, dtype="object")
    out.loc[out["V_minus_H_dB"] > 0, "preferred_pol"] = "V"
    out.loc[out["V_minus_H_dB"] < 0, "preferred_pol"] = "H"
    out.loc[out["V_minus_H_dB"] == 0, "preferred_pol"] = "equal"

    return out


import numpy as np
import matplotlib.pyplot as plt

import numpy as np
import matplotlib.pyplot as plt

def plot_subject_rcs_ieee(
    df,
    freq_hz,
    segment_type="single",
    subjects=None,
    polarization=None,
    plot_dbsm=False,
    title=None,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    column_width=3.5,      # IEEE one-column width
    row_height=1.25,       # height per subject row
    jitter=0.012,
    marker_size=28,
    show_mean=True,
    sharey=True,
    label_mode="name",     # "name" or "number"
    number_prefix="",      # "", "S", etc.
    savepath=None,
    dpi=600,
):
    """
    Plot RCS vs distance in stacked IEEE-style subplots (one subject per row).

    Parameters
    ----------
    label_mode : str
        "name"   -> panel labels use subject names
        "number" -> panel labels use subject index (1,2,3,...) or prefixed form
    number_prefix : str
        Used only when label_mode="number", e.g. "S" gives S1, S2, ...
    """

    # -----------------------------
    # Filter DataFrame
    # -----------------------------
    df_plot = df[
        (df[freq_col] == freq_hz) &
        (df[segtype_col].astype(str).str.lower() == segment_type.lower())
    ].copy()

    # Normalize polarization labels
    pol_map = {
        "v": "V",
        "vertical": "V",
        "h": "H",
        "horizontal": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_plot[pol_col] = df_plot[pol_col].apply(normalize_pol)

    if subjects is not None:
        df_plot = df_plot[df_plot[subject_col].isin(subjects)].copy()

    if polarization is not None:
        pol_key = str(polarization).strip().lower()
        if pol_key not in pol_map:
            raise ValueError(
                "polarization must be one of: None, 'V', 'H', 'vertical', 'horizontal'"
            )
        pol_val = pol_map[pol_key]
        df_plot = df_plot[df_plot[pol_col] == pol_val].copy()

    if df_plot.empty:
        print(
            f"No data found for freq_hz={freq_hz}, "
            f"segment_type='{segment_type}', polarization={polarization}."
        )
        return

    # -----------------------------
    # Unit conversion
    # -----------------------------
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    # -----------------------------
    # Subject ordering
    # -----------------------------
    if subjects is None:
        subjects_use = sorted(df_plot[subject_col].dropna().unique())
    else:
        subjects_use = [s for s in subjects if s in df_plot[subject_col].unique()]

    if len(subjects_use) == 0:
        print("No matching subjects found.")
        return

    # -----------------------------
    # Figure setup
    # -----------------------------
    n_subj = len(subjects_use)
    fig_height = row_height * n_subj + 0.45

    fig, axes = plt.subplots(
        n_subj, 1,
        figsize=(column_width, fig_height),
        sharex=True,
        sharey=sharey,
        constrained_layout=True
    )

    if n_subj == 1:
        axes = [axes]

    # Styles
    color_map = {"V": "tab:blue", "H": "tab:orange"}
    marker_map = {"V": "o", "H": "s"}
    line_map   = {"V": "-", "H": "--"}
    offset_map = {"V": -jitter/2, "H": +jitter/2}

    if polarization is not None:
        pols_to_plot = [pol_map[str(polarization).strip().lower()]]
    else:
        pols_to_plot = [p for p in ["V", "H"] if p in df_plot[pol_col].unique()]

    # -----------------------------
    # Plot each subject
    # -----------------------------
    for subj_idx, (ax, subj) in enumerate(zip(axes, subjects_use), start=1):
        df_subj = df_plot[df_plot[subject_col] == subj].copy()

        for pol in pols_to_plot:
            df_pol = df_subj[df_subj[pol_col] == pol].copy()
            if df_pol.empty:
                continue

            # plot raw points
            for dist in sorted(df_pol[dist_col].dropna().unique()):
                df_dist = df_pol[df_pol[dist_col] == dist]
                y = df_dist["sigma_plot"].dropna().to_numpy()
                if len(y) == 0:
                    continue

                local_jitter = (
                    np.arange(len(y)) - (len(y) - 1) / 2.0
                ) * jitter * 0.45

                x = np.full(len(y), float(dist)) + offset_map[pol] + local_jitter

                # label only once total for legend cleanliness
                label = pol if subj_idx == 1 and dist == sorted(df_pol[dist_col].dropna().unique())[0] else None

                ax.scatter(
                    x, y,
                    s=marker_size,
                    marker=marker_map[pol],
                    color=color_map[pol],
                    edgecolors="black",
                    linewidths=0.5,
                    alpha=0.9,
                    label=label,
                    zorder=3,
                )

            # optional mean line across distances
            if show_mean:
                mean_df = (
                    df_pol.groupby(dist_col, as_index=False)["sigma_plot"]
                    .mean()
                    .sort_values(dist_col)
                )
                if len(mean_df) > 0:
                    ax.plot(
                        mean_df[dist_col].to_numpy() + offset_map[pol],
                        mean_df["sigma_plot"].to_numpy(),
                        line_map[pol],
                        color=color_map[pol],
                        linewidth=1.0,
                        alpha=0.95,
                        zorder=2,
                    )

        # panel label
        if label_mode.lower() == "name":
            panel_label = str(subj)
        elif label_mode.lower() == "number":
            panel_label = f"{number_prefix}{subj_idx}"
        else:
            raise ValueError("label_mode must be 'name' or 'number'")

        ax.text(
            0.02, 0.92, panel_label,
            transform=ax.transAxes,
            ha="left", va="top",
            fontsize=8,
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="white",
                edgecolor="0.5",
                alpha=0.95
            )
        )

        ax.set_ylabel(y_label, fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.35)

    # x-axis formatting
    dists = sorted(df_plot[dist_col].dropna().unique())
    if len(dists) > 0:
        axes[-1].set_xticks(dists)
        axes[-1].set_xlim(min(dists) - 0.15, max(dists) + 0.15)

    axes[-1].set_xlabel("Distance (m)", fontsize=8)

    # title
    freq_ghz = freq_hz / 1e9
    if title is None:
        if polarization is None:
            pol_str = "All Polarizations"
        else:
            pol_str = "Vertical" if pols_to_plot[0] == "V" else "Horizontal"

        title = f"{freq_ghz:g} GHz, {segment_type.capitalize()} Segments, {pol_str}, {unit_str}"

    fig.suptitle(title, fontsize=9)

    # clean legend: unique entries only
    handles, labels = axes[0].get_legend_handles_labels()
    unique = {}
    for h, l in zip(handles, labels):
        if l not in unique and l != "":
            unique[l] = h

    if unique:
        axes[0].legend(
            unique.values(),
            unique.keys(),
            loc="upper right",
            fontsize=7,
            frameon=True,
            title=None
        )

    if savepath is not None:
        plt.savefig(savepath, dpi=dpi, bbox_inches="tight")

    plt.show()

import numpy as np
import matplotlib.pyplot as plt

def plot_all_subjects_rcs_by_pol(
    df,
    freq_hz,
    segment_type="single",
    subjects=None,
    plot_dbsm=False,
    title=None,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    figsize=(6.8, 5.0),
    jitter=0.012,
    marker_size=42,
    show_mean=True,
    sharey=True,
    label_mode="name",       # "name" or "number"
    number_prefix="Subject ",
    legend=True,
):
    """
    Plot all subjects on one figure for a given frequency, with
    separate subplots for V and H polarization.

    Top subplot    : VV polarization
    Bottom subplot : HH polarization
    """

    # -----------------------------
    # Base filtering
    # -----------------------------
    df_plot = df[
        (df[freq_col] == freq_hz) &
        (df[segtype_col].astype(str).str.lower() == segment_type.lower())
    ].copy()

    # Normalize polarization labels
    pol_map = {
        "v": "V",
        "vertical": "V",
        "h": "H",
        "horizontal": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_plot[pol_col] = df_plot[pol_col].apply(normalize_pol)

    if subjects is not None:
        df_plot = df_plot[df_plot[subject_col].isin(subjects)].copy()

    if df_plot.empty:
        print(
            f"No data found for freq_hz={freq_hz}, "
            f"segment_type='{segment_type}'."
        )
        return

    # -----------------------------
    # Unit conversion
    # -----------------------------
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    # -----------------------------
    # Subject ordering
    # -----------------------------
    if subjects is None:
        subjects_use = sorted(df_plot[subject_col].dropna().unique())
    else:
        subjects_use = [s for s in subjects if s in df_plot[subject_col].unique()]

    if len(subjects_use) == 0:
        print("No matching subjects found.")
        return

    # -----------------------------
    # Marker styles by subject
    # -----------------------------
    marker_list = [
        "o", "s", "^", "D", "v", "P", "X", "<", ">", "*", "h", "8"
    ]

    subject_marker_map = {
        subj: marker_list[i % len(marker_list)]
        for i, subj in enumerate(subjects_use)
    }

    # Small subject-dependent offsets so markers at same distance do not fully overlap
    n_subj = len(subjects_use)
    if n_subj == 1:
        subj_offsets = {subjects_use[0]: 0.0}
    else:
        offsets = np.linspace(-jitter, jitter, n_subj)
        subj_offsets = {subj: offsets[i] for i, subj in enumerate(subjects_use)}

    # Panel colors
    pol_color_map = {
        "V": "tab:blue",
        "H": "tab:orange",
    }

    # -----------------------------
    # Figure setup
    # -----------------------------
    fig, axes = plt.subplots(
        2, 1,
        figsize=figsize,
        sharex=True,
        sharey=sharey,
        constrained_layout=False
    )

    pol_order = ["V", "H"]
    pol_titles = {
        "V": "VV Polarization",
        "H": "HH Polarization",
    }

    legend_handles = []
    legend_labels = []

    # -----------------------------
    # Plot each polarization panel
    # -----------------------------
    for ax, pol in zip(axes, pol_order):
        df_pol = df_plot[df_plot[pol_col] == pol].copy()

        if df_pol.empty:
            ax.text(
                0.5, 0.5, f"No {pol} data",
                transform=ax.transAxes,
                ha="center", va="center", fontsize=10
            )
            ax.set_ylabel(y_label)
            ax.grid(True, linestyle="--", alpha=0.35)
            ax.set_title(pol_titles[pol], fontsize=11)
            continue

        for subj_idx, subj in enumerate(subjects_use, start=1):
            df_subj = df_pol[df_pol[subject_col] == subj].copy()
            if df_subj.empty:
                continue

            marker = subject_marker_map[subj]
            color = pol_color_map[pol]
            offset = subj_offsets[subj]

            if label_mode.lower() == "name":
                label = str(subj)
            elif label_mode.lower() == "number":
                label = f"{number_prefix}{subj_idx}"
            else:
                raise ValueError("label_mode must be 'name' or 'number'")

            # Raw points
            for dist in sorted(df_subj[dist_col].dropna().unique()):
                df_dist = df_subj[df_subj[dist_col] == dist]
                y = df_dist["sigma_plot"].dropna().to_numpy()
                if len(y) == 0:
                    continue

                local_jitter = (
                    np.arange(len(y)) - (len(y) - 1) / 2.0
                ) * (jitter * 0.35)

                x = np.full(len(y), float(dist)) + offset + local_jitter

                sc = ax.scatter(
                    x, y,
                    s=marker_size,
                    marker=marker,
                    color=color,
                    edgecolors="black",
                    linewidths=0.5,
                    alpha=0.9,
                    label=label,
                    zorder=3,
                )

                # Save only one handle per subject for legend
                if pol == "V" and label not in legend_labels:
                    legend_handles.append(sc)
                    legend_labels.append(label)

            # Mean line
            if show_mean:
                mean_df = (
                    df_subj.groupby(dist_col, as_index=False)["sigma_plot"]
                    .mean()
                    .sort_values(dist_col)
                )
                if len(mean_df) > 0:
                    ax.plot(
                        mean_df[dist_col].to_numpy() + offset,
                        mean_df["sigma_plot"].to_numpy(),
                        linestyle="--",
                        color=color,
                        linewidth=1.0,
                        alpha=0.9,
                        zorder=2,
                    )

        ax.set_title(pol_titles[pol], fontsize=11)
        ax.set_ylabel(y_label)
        ax.grid(True, linestyle="--", alpha=0.35)

    # -----------------------------
    # X-axis formatting
    # -----------------------------
    dists = sorted(df_plot[dist_col].dropna().unique())
    if len(dists) > 0:
        axes[-1].set_xticks(dists)
        axes[-1].set_xlim(min(dists) - 0.08, max(dists) + 0.28)

    axes[-1].set_xlabel("Distance (m)")

    # -----------------------------
    # Figure title
    # -----------------------------
    freq_ghz = freq_hz / 1e9
    if title is None:
        title = f"{freq_ghz:g} GHz RCS Profiles ({segment_type.capitalize()} Segments, {unit_str})"

    fig.suptitle(title, fontsize=12)

    # -----------------------------
    # Legend
    # -----------------------------
    if legend and len(legend_handles) > 0:
        axes[0].legend(
            legend_handles,
            legend_labels,
            title="Subject",
            fontsize=9,
            title_fontsize=10,
            loc="upper left",
            bbox_to_anchor=(1.02, 1.00),
            borderaxespad=0.0,
            ncol=1,
            frameon=True,
        )

    plt.tight_layout(rect=[0, 0, 0.82, 0.95])
    plt.show()
# Import Data
# ==========================================================
# Import + Filter: build DataFrame and save filtered copies
# ==========================================================

# Discover and parse all human files
files = discover_human_files(DATA_DIR, skip_dirs=("cal",))
df_files = pd.DataFrame([parse_filename_v2(f) for f in files])

print(f"Discovered {len(df_files)} human CSV files across "
      f"{df_files['subject'].nunique()} subjects: "
      f"{sorted(df_files['subject'].unique())}")
print(df_files.groupby(['subject', 'freq_hz', 'dist_m', 'pol_tx']).size()
      .rename('n_files').reset_index())

display(df_files.head())
# Process Human Data
### View Multiple Segments
import numpy as np
import pandas as pd

# ==========================================================
# VIEWER CELL — manually explore and trim data
# ==========================================================
# --- Select file ---
subject = "jalen"
dist_m  = 1.5
freq_hz = 24e9      # 2.4e9 or 24e9
pol_tx  = "H"        # "V" or "H"
dset    = 0

# --- Calibration version ---
cal_plate_cm = 12   # 18 or 16 for 2.4 GHz; 12 for 24 GHz
cal_version  = "new" # "new" or "old"

# --- Base trim window ---
start_sample = 2000
end_sample   = 3500  

# ==========================================================
# SWEEP CONTROL
# Comment/uncomment ONE of these
# ==========================================================

sweep_mode   = "start"
sweep_values = range(0, 3100, 25)

# sweep_mode   = "end"
# sweep_values = range(2200, 3200, 10)

# --- Filter options ---
use_filter  = True
fc          = 1.0
filt_order  = 6
fs          = 100.0

# Load once outside loop
row   = lookup_file_row(df_files, subject, dist_m, freq_hz, pol_tx, dset)
cal   = load_calibration(freq_hz, dist_m, pol_tx, cal_plate_cm, cal_version)
df_iq, N = load_iq(row)

# Store results
sigma_results = []

for val in sweep_values:
    this_start = start_sample
    this_end   = end_sample

    if sweep_mode == "start":
        this_start = val
    elif sweep_mode == "end":
        this_end = val
    else:
        raise ValueError("sweep_mode must be 'start' or 'end'")

    print_measurement_summary(
        row, cal, N, this_start, this_end,
        cal_plate_cm, pol_tx, cal_version, fs=fs
    )

    df_result = quick_analysis(
        idata=df_iq["I"],
        qdata=df_iq["Q"],
        gain=row.gain,
        start_sample=this_start,
        end_sample=this_end,
        Ae=cal["Ae"], Pe=cal["Pe"], gen_coeffs=False,
        # Ae=None, Pe=None, gen_coeffs=True,
        # Ae=0.844396, Pe=-0.059875, gen_coeffs=False, # Vertical, 1.0, dset1
        # Ae=0.375061, Pe=-0.229994 ,gen_coeffs=False, # horiz., 1.5, dset1
        use_filter=use_filter,
        fc=fc,
        filt_order=filt_order,
        fs=fs,
        freq_rf=freq_hz,
        A_cal=cal["A_cal"],
        sigma_cal=cal["sigma_cal"],
        gen_plots=False,  # skip plots for sweep runs to save time
    )

    display(df_result.drop(columns=["disp_cm"]))

    sigma_results.append({
        "swept_param": sweep_mode,
        "swept_value": val,
        "start_sample": this_start,
        "end_sample": this_end,
        "ae": df_result["ae"].iloc[0],
        "pe": df_result["pe"].iloc[0],
        "sigma_human": df_result["sigma_human"].iloc[0],
    })

sigma_df = pd.DataFrame(sigma_results)

print("\n=== Sigma Human Summary ===")
print(
    sigma_df[
        ["swept_param", "swept_value", "start_sample", "end_sample", "ae", "pe", "sigma_human"]
    ].to_string(index=False)
)
### Trim Segment (single)
# ==========================================================
# VIEWER CELL — manually explore and trim data
# ==========================================================
# Adjust params below, re-run to iterate. Save trim with the next cell.

# --- Select file ---
subject = "jalen"
dist_m  = 1.5
freq_hz = 24e9      # 2.4e9 or 24e9
pol_tx  = "H"        # "V" or "H"
dset    = 0

# --- Calibration version ---
cal_plate_cm = 12   # 18 or 16 for 2.4 GHz; 12 for 24 GHz
cal_version  = "new" # "new" or "old"

# --- Trim window (absolute sample indices at fs=1000) ---
##################################################################################
############################ 2.4 GHz vertical values #############################
##################################################################################

############# 1.0 m distance #############
# start_sample = None  # ERCS=0.345723  1.0m, Vtx, dset=0 
# end_sample   = 490

############# 1.5 m distance #############
# start_sample = 105  # ERCS=0.111405  1.5m, Vtx, dset=0 | single
# end_sample   = 625

##################################################################################
############################ 2.4 GHz horizontal values ###########################
##################################################################################

############# 1.0 m distance #############
# start_sample = 2050  # ERCS=0.280883   1.0m, Htx, dset=1 
# end_sample   = 2575

############# 1.5 m distance #############
# start_sample = 650  # ERCS=0.284428   1.5m, Htx, dset=0 
# end_sample   = 1110

##################################################################################
############################ 24 GHz vertical values ##############################
##################################################################################

############# 1.0 m distance #############
# start_sample = None  # ERCS=0.210698  1.0m, Vtx, dset=1 | single
# end_sample   = None

# start_sample = 0  # ERCS=0.331211  1.0m, Vtx, dset=1 | single
# end_sample   = 550

############# 1.5 m distance #############
# start_sample = 000  # ERCS=0.201897  1.5m, Vtx, dset=0 | single
# end_sample   = 2500

# start_sample = 3030  # ERCS=0.237350   1.5m, Vtx, dset=1 | single
# end_sample   = 3500


##################################################################################
############################ 24 GHz horizontal values ############################
##################################################################################

############# 1.0 m distance #############
# start_sample = 3025  # ERCS=0.202987   1.0m, Htx, dset=0 | single
# end_sample   = 3490

# start_sample = 800  # ERCS=0.20521   1.0m, Htx, dset=1 | single
# end_sample   = 2050

# start_sample = 1100  # ERCS=0.204597   1.0m, Htx, dset=1 | single
# end_sample   = 2625

############# 1.5 m distance #############
# start_sample = 1850  # ERCS=0.218085   1.5m, Htx, dset=0 | single
# end_sample   = 2150

# start_sample = 1400  # ERCS=0.202971   1.5m, Htx, dset=0 | single
# end_sample   = 2125

# start_sample = 1850  # ERCS=0.209839   1.5m, Htx, dset=0 | single
# end_sample   = 2250

##################################################################################
############################ working horizontal values ###########################
##################################################################################
start_sample = 800  # ERCS=0.204597   1.0m, Htx, dset=1 | single
end_sample   = 3100


# --- Filter options ---
use_filter  = True
fc          = 1.0
filt_order  = 6
fs          = 100.0

row   = lookup_file_row(df_files, subject, dist_m, freq_hz, pol_tx, dset)
cal   = load_calibration(freq_hz, dist_m, pol_tx, cal_plate_cm, cal_version)
df_iq, N = load_iq(row)

print_measurement_summary(row, cal, N, start_sample, end_sample,
                          cal_plate_cm, pol_tx, cal_version, fs=fs)

df_result = quick_analysis(
    idata=df_iq["I"], qdata=df_iq["Q"],
    gain=row.gain,
    start_sample=start_sample, end_sample=end_sample,
    Ae=cal["Ae"], Pe=cal["Pe"], gen_coeffs=False,
    # Ae=None, Pe=None, gen_coeffs=True,
    # Ae=0.934396, Pe=-0.059875, gen_coeffs=False, # Vertical, 1.0, dset1
    # Ae=0.375061, Pe=-0.229994, gen_coeffs=False, # horiz., 1.5, dset1
    use_filter=use_filter, fc=fc, filt_order=filt_order, fs=fs,
    freq_rf=freq_hz,
    A_cal=cal["A_cal"], sigma_cal=cal["sigma_cal"],
)

display(df_result.drop(columns=["disp_cm"]))
# ==========================================================
# SAVE CELL — append current trim as a new segment
# ==========================================================
# Run AFTER the viewer cell when happy with the trim.

segment_type = "multi"   # "multi" or "single"
segment      = None      # None = auto-increment within this type
notes        = ""

save_result(
    df_result,
    subject=subject, dist_m=dist_m, freq_hz=freq_hz,
    pol_tx=pol_tx, dset=dset,
    cal_plate_cm=cal_plate_cm, cal_version=cal_version,
    use_filter=use_filter, fc=fc, filt_order=filt_order, fs=fs,
    segment_type=segment_type,
    segment=segment, notes=notes,
)

# Show all segments currently saved for this file
print()
display(get_saved_segments(subject=subject, dist_m=dist_m, freq_hz=freq_hz,
                           pol_tx=pol_tx, dset=dset,
                           cal_plate_cm=cal_plate_cm, cal_version=cal_version)
        [["segment_type", "segment", "start_sample", "end_sample",
          "N_samples_used", "r", "sigma_human", "peak_to_peak_cm", "notes"]]
        .sort_values(["segment_type", "segment"]))
### Store and Print Summary
import json
import pandas as pd

# -------------------------------
# Load entire JSON into a DataFrame
# -------------------------------
results_path = OUT_DIR / "results.json"
with open(results_path, "r") as f:
    records = json.load(f)

df_all = pd.DataFrame(records)

# -------------------------------
# Filter by segment_type
# -------------------------------
df_single = df_all[df_all["segment_type"] == "single"].copy()
df_multi  = df_all[df_all["segment_type"] == "multi"].copy()

sub = "jalen"
view_freq = 24e9

# print("All records:")
# display(df_all)

# print("\nSingle segments:")
# display(df_single[df_all["subject"] == sub])

print("\nSingle segments:")
display(df_single[(df_single["subject"] == sub) & (df_single["freq_hz"] == view_freq)])



# print("\nMulti segments:")
# display(df_multi[df_all["subject"] == sub])

print("\nMulti segments:")
display(df_multi[(df_multi["subject"] == sub) & (df_multi["freq_hz"] == view_freq)])
### Reload Cells
# ==========================================================
# RELOAD CELL — pull a saved segment's settings back into viewer state
# ==========================================================

# --- Select file ---
subject = "victor"
dist_m  = 1.0
freq_hz = 2.4e9      # 2.4e9 or 24e9
pol_tx  = "V"        # "V" or "H"
dset    = 0

# --- Calibration version ---
cal_plate_cm = 18    # 18 or 16 for 2.4 GHz; 12 for 24 GHz
cal_version  = "new" # "new" or "old"

reload_segment_type = "single"   # "multi" or "single"
reload_segment      = 1

rec = load_segment(subject, dist_m, freq_hz, pol_tx, dset,
                   cal_plate_cm, cal_version,
                   segment_type=reload_segment_type,
                   segment=reload_segment)

start_sample = rec["start_sample"]
end_sample   = rec["end_sample"]
use_filter   = rec["use_filter"]
fc           = rec["fc"]
filt_order   = rec["filt_order"]
fs           = rec["fs"]

print(f"✓ Loaded {reload_segment_type}-segment {reload_segment}:")
print(f"  start_sample = {start_sample}")
print(f"  end_sample   = {end_sample}")
print(f"  filter       = {'ON' if use_filter else 'OFF'} "
      f"(fc={fc}, order={filt_order}, fs={fs})")
print(f"  notes        : {rec['notes']!r}")
print(f"  saved_at     : {rec['saved_at']}")
print()
print("→ Re-run the viewer cell to reprocess with these settings.")
df_result = quick_analysis(
    idata=df_iq["I"], qdata=df_iq["Q"],
    gain=row.gain,
    start_sample=start_sample, end_sample=end_sample,
    Ae=cal["Ae"], Pe=cal["Pe"], gen_coeffs=False,
    use_filter=use_filter, fc=fc, filt_order=filt_order, fs=fs,
    freq_rf=freq_hz,
    A_cal=cal["A_cal"], sigma_cal=cal["sigma_cal"],
)

display(df_result.drop(columns=["disp_cm"]))
# Analysis
## All RCS Profiles
import numpy as np
import matplotlib.pyplot as plt

def plot_rcs_profile_grid(
    df,
    freqs_hz=(2.4e9, 24e9),
    segment_types=("single", "multi"),
    subjects=None,
    plot_dbsm=False,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    figsize=(10, 12),
    jitter=0.012,
    marker_size=42,
    show_mean=True,
    sharey=False,
    label_mode="name",       # "name" or "number"
    number_prefix="Subject ",
    legend=True,
):
    """
    Plot a 4-row x 2-column grid of RCS profiles:
        columns: single / multi
        rows:    2.4 GHz VV, 2.4 GHz HH, 24 GHz VV, 24 GHz HH

    Parameters
    ----------
    freqs_hz : tuple
        Frequencies to plot, typically (2.4e9, 24e9)
    segment_types : tuple
        Segment types to plot, typically ("single", "multi")
    """

    # -----------------------------
    # Normalize/filter base DataFrame
    # -----------------------------
    df_plot = df.copy()

    pol_map = {
        "v": "V",
        "vertical": "V",
        "h": "H",
        "horizontal": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_plot[pol_col] = df_plot[pol_col].apply(normalize_pol)

    if subjects is not None:
        df_plot = df_plot[df_plot[subject_col].isin(subjects)].copy()

    if df_plot.empty:
        print("No data found after subject filtering.")
        return

    # -----------------------------
    # Unit conversion
    # -----------------------------
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    # -----------------------------
    # Subject ordering / markers
    # -----------------------------
    if subjects is None:
        subjects_use = sorted(df_plot[subject_col].dropna().unique())
    else:
        subjects_use = [s for s in subjects if s in df_plot[subject_col].unique()]

    if len(subjects_use) == 0:
        print("No matching subjects found.")
        return

    marker_list = [
        "o", "s", "^", "D", "v", "P", "X", "<", ">", "*", "h", "8"
    ]
    subject_marker_map = {
        subj: marker_list[i % len(marker_list)]
        for i, subj in enumerate(subjects_use)
    }

    n_subj = len(subjects_use)
    if n_subj == 1:
        subj_offsets = {subjects_use[0]: 0.0}
    else:
        offsets = np.linspace(-jitter, jitter, n_subj)
        subj_offsets = {subj: offsets[i] for i, subj in enumerate(subjects_use)}

    pol_color_map = {
        "V": "tab:blue",
        "H": "tab:orange",
    }

    pol_titles = {
        "V": "VV Polarization",
        "H": "HH Polarization",
    }

    # -----------------------------
    # Figure layout
    # -----------------------------
    nrows = len(freqs_hz) * 2   # each frequency gets VV + HH row
    ncols = len(segment_types)  # single, multi

    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=figsize,
        sharex=True,
        sharey=sharey,
        constrained_layout=False
    )

    # if only one col/row, force 2D indexing
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1:
        axes = axes[np.newaxis, :]
    elif ncols == 1:
        axes = axes[:, np.newaxis]

    # -----------------------------
    # Column titles
    # -----------------------------
    for col_idx, segtype in enumerate(segment_types):
        col_title = f"{segtype.capitalize()} Segments"
        axes[0, col_idx].set_title(col_title, fontsize=12, pad=10)

    # -----------------------------
    # Legend հավաքում (collect once)
    # -----------------------------
    legend_handles = []
    legend_labels = []

    # -----------------------------
    # Plot panels
    # -----------------------------
    for f_idx, freq_hz in enumerate(freqs_hz):
        freq_ghz = freq_hz / 1e9

        # row indices for this frequency
        row_v = 2 * f_idx
        row_h = 2 * f_idx + 1

        for c_idx, segtype in enumerate(segment_types):
            for pol, row_idx in zip(["V", "H"], [row_v, row_h]):
                ax = axes[row_idx, c_idx]

                df_panel = df_plot[
                    (df_plot[freq_col] == freq_hz) &
                    (df_plot[segtype_col].astype(str).str.lower() == segtype.lower()) &
                    (df_plot[pol_col] == pol)
                ].copy()

                if df_panel.empty:
                    ax.text(
                        0.5, 0.5, "No data",
                        transform=ax.transAxes,
                        ha="center", va="center", fontsize=10
                    )
                    ax.grid(True, linestyle="--", alpha=0.35)
                    continue

                for subj_idx, subj in enumerate(subjects_use, start=1):
                    df_subj = df_panel[df_panel[subject_col] == subj].copy()
                    if df_subj.empty:
                        continue

                    marker = subject_marker_map[subj]
                    color = pol_color_map[pol]
                    offset = subj_offsets[subj]

                    if label_mode.lower() == "name":
                        label = str(subj)
                    elif label_mode.lower() == "number":
                        label = f"{number_prefix}{subj_idx}"
                    else:
                        raise ValueError("label_mode must be 'name' or 'number'")

                    # raw points
                    for dist in sorted(df_subj[dist_col].dropna().unique()):
                        df_dist = df_subj[df_subj[dist_col] == dist]
                        y = df_dist["sigma_plot"].dropna().to_numpy()
                        if len(y) == 0:
                            continue

                        local_jitter = (
                            np.arange(len(y)) - (len(y) - 1) / 2.0
                        ) * (jitter * 0.35)

                        x = np.full(len(y), float(dist)) + offset + local_jitter

                        sc = ax.scatter(
                            x, y,
                            s=marker_size,
                            marker=marker,
                            color=color,
                            edgecolors="black",
                            linewidths=0.5,
                            alpha=0.9,
                            zorder=3,
                        )

                        # collect one legend handle per subject
                        if label not in legend_labels:
                            legend_handles.append(sc)
                            legend_labels.append(label)

                    # mean line
                    if show_mean:
                        mean_df = (
                            df_subj.groupby(dist_col, as_index=False)["sigma_plot"]
                            .mean()
                            .sort_values(dist_col)
                        )
                        if len(mean_df) > 0:
                            ax.plot(
                                mean_df[dist_col].to_numpy() + offset,
                                mean_df["sigma_plot"].to_numpy(),
                                linestyle="--",
                                color=color,
                                linewidth=1.0,
                                alpha=0.9,
                                zorder=2,
                            )

                # panel cosmetics
                ax.grid(True, linestyle="--", alpha=0.35)

                # row labels on leftmost column
                if c_idx == 0:
                    ax.set_ylabel(y_label, fontsize=10)
                    ax.text(
                        -0.28, 0.5,
                        f"{freq_ghz:g} GHz\n{pol_titles[pol]}",
                        transform=ax.transAxes,
                        rotation=90,
                        ha="center", va="center",
                        fontsize=11
                    )

    # -----------------------------
    # X-axis formatting
    # -----------------------------
    dists = sorted(df_plot[dist_col].dropna().unique())
    if len(dists) > 0:
        for ax in axes.flatten():
            ax.set_xticks(dists)
            ax.set_xlim(min(dists) - 0.1, max(dists) + 0.1)

    # only bottom row gets x-labels
    for c_idx in range(ncols):
        axes[-1, c_idx].set_xlabel("Distance (m)", fontsize=11)

    # -----------------------------
    # Figure title
    # -----------------------------
    fig.suptitle(f"RCS Profiles ({unit_str})", fontsize=14)

    # -----------------------------
    # Legend
    # -----------------------------
    if legend and len(legend_handles) > 0:
        fig.legend(
            legend_handles,
            legend_labels,
            title="Subject",
            fontsize=9,
            title_fontsize=10,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.03),
            ncol=len(legend_labels),
            frameon=True,
        )

    plt.tight_layout(rect=[0.04, 0.03, 0.90, 0.96])
    plt.show()
plot_rcs_profile_grid(
    df_all,
    freqs_hz=(2.4e9, 24e9),
    segment_types=("single", "multi"),
    plot_dbsm=False,
    label_mode="number",
    number_prefix="Subject ",
    figsize=(10, 12),
)
## 2.4 GHz RCS Profiles
import numpy as np
import matplotlib.pyplot as plt

def plot_rcs_profile_grid(
    df,
    freqs_hz=(2.4e9, 24e9),   # can be a float or a sequence
    segment_types=("single", "multi"),
    subjects=None,
    plot_dbsm=False,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    figsize=None,
    jitter=0.012,
    marker_size=42,
    show_mean=True,
    sharey=False,
    label_mode="name",       # "name" or "number"
    number_prefix="Subject ",
    legend=True,
):
    """
    Plot RCS profile grid.

    If freqs_hz has:
      - 1 frequency: 2 rows x 2 cols
      - 2 frequencies: 4 rows x 2 cols
    """

    # -----------------------------
    # Allow single frequency input
    # -----------------------------
    if np.isscalar(freqs_hz):
        freqs_hz = (float(freqs_hz),)
    else:
        freqs_hz = tuple(freqs_hz)

    # -----------------------------
    # Normalize/filter base DataFrame
    # -----------------------------
    df_plot = df.copy()

    pol_map = {
        "v": "V",
        "vertical": "V",
        "h": "H",
        "horizontal": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_plot[pol_col] = df_plot[pol_col].apply(normalize_pol)

    if subjects is not None:
        df_plot = df_plot[df_plot[subject_col].isin(subjects)].copy()

    if df_plot.empty:
        print("No data found after subject filtering.")
        return

    # -----------------------------
    # Unit conversion
    # -----------------------------
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    # -----------------------------
    # Subject ordering / markers
    # -----------------------------
    if subjects is None:
        subjects_use = sorted(df_plot[subject_col].dropna().unique())
    else:
        subjects_use = [s for s in subjects if s in df_plot[subject_col].unique()]

    if len(subjects_use) == 0:
        print("No matching subjects found.")
        return

    marker_list = [
        "o", "s", "^", "D", "v", "P", "X", "<", ">", "*", "h", "8"
    ]
    subject_marker_map = {
        subj: marker_list[i % len(marker_list)]
        for i, subj in enumerate(subjects_use)
    }

    n_subj = len(subjects_use)
    if n_subj == 1:
        subj_offsets = {subjects_use[0]: 0.0}
    else:
        offsets = np.linspace(-jitter, jitter, n_subj)
        subj_offsets = {subj: offsets[i] for i, subj in enumerate(subjects_use)}

    pol_color_map = {
        "V": "tab:blue",
        "H": "tab:orange",
    }

    pol_titles = {
        "V": "VV Polarization",
        "H": "HH Polarization",
    }

    # -----------------------------
    # Figure layout
    # -----------------------------
    nrows = len(freqs_hz) * 2
    ncols = len(segment_types)

    if figsize is None:
        figsize = (8.5, 3.0 * nrows)

    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=figsize,
        sharex=True,
        sharey=sharey,
        constrained_layout=False
    )

    # Force 2D indexing
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1:
        axes = axes[np.newaxis, :]
    elif ncols == 1:
        axes = axes[:, np.newaxis]

    # -----------------------------
    # Column titles
    # -----------------------------
    for col_idx, segtype in enumerate(segment_types):
        axes[0, col_idx].set_title(f"{segtype.capitalize()} Segments", fontsize=12, pad=10)

    # -----------------------------
    # Legend collection
    # -----------------------------
    legend_handles = []
    legend_labels = []

    # -----------------------------
    # Plot panels
    # -----------------------------
    for f_idx, freq_hz in enumerate(freqs_hz):
        freq_ghz = freq_hz / 1e9

        row_v = 2 * f_idx
        row_h = 2 * f_idx + 1

        for c_idx, segtype in enumerate(segment_types):
            for pol, row_idx in zip(["V", "H"], [row_v, row_h]):
                ax = axes[row_idx, c_idx]

                df_panel = df_plot[
                    (df_plot[freq_col] == freq_hz) &
                    (df_plot[segtype_col].astype(str).str.lower() == segtype.lower()) &
                    (df_plot[pol_col] == pol)
                ].copy()

                if df_panel.empty:
                    ax.text(
                        0.5, 0.5, "No data",
                        transform=ax.transAxes,
                        ha="center", va="center", fontsize=10
                    )
                    ax.grid(True, linestyle="--", alpha=0.35)
                    continue

                for subj_idx, subj in enumerate(subjects_use, start=1):
                    df_subj = df_panel[df_panel[subject_col] == subj].copy()
                    if df_subj.empty:
                        continue

                    marker = subject_marker_map[subj]
                    color = pol_color_map[pol]
                    offset = subj_offsets[subj]

                    if label_mode.lower() == "name":
                        label = str(subj)
                    elif label_mode.lower() == "number":
                        label = f"{number_prefix}{subj_idx}"
                    else:
                        raise ValueError("label_mode must be 'name' or 'number'")

                    for dist in sorted(df_subj[dist_col].dropna().unique()):
                        df_dist = df_subj[df_subj[dist_col] == dist]
                        y = df_dist["sigma_plot"].dropna().to_numpy()
                        if len(y) == 0:
                            continue

                        local_jitter = (
                            np.arange(len(y)) - (len(y) - 1) / 2.0
                        ) * (jitter * 0.35)

                        x = np.full(len(y), float(dist)) + offset + local_jitter

                        sc = ax.scatter(
                            x, y,
                            s=marker_size,
                            marker=marker,
                            color=color,
                            edgecolors="black",
                            linewidths=0.5,
                            alpha=0.9,
                            zorder=3,
                        )

                        if label not in legend_labels:
                            legend_handles.append(sc)
                            legend_labels.append(label)

                    if show_mean:
                        mean_df = (
                            df_subj.groupby(dist_col, as_index=False)["sigma_plot"]
                            .mean()
                            .sort_values(dist_col)
                        )
                        if len(mean_df) > 0:
                            ax.plot(
                                mean_df[dist_col].to_numpy() + offset,
                                mean_df["sigma_plot"].to_numpy(),
                                linestyle="--",
                                color=color,
                                linewidth=1.0,
                                alpha=0.9,
                                zorder=2,
                            )

                ax.grid(True, linestyle="--", alpha=0.35)

                if c_idx == 0:
                    ax.set_ylabel(y_label, fontsize=10)
                    ax.text(
                        -0.28, 0.5,
                        f"{pol_titles[pol]}",
                        transform=ax.transAxes,
                        rotation=90,
                        ha="center", va="center",
                        fontsize=11
                    )

    # -----------------------------
    # X-axis formatting
    # -----------------------------
    dists = sorted(df_plot[dist_col].dropna().unique())
    if len(dists) > 0:
        for ax in axes.flatten():
            ax.set_xticks(dists)
            ax.set_xlim(min(dists) - 0.1, max(dists) + 0.1)

    for c_idx in range(ncols):
        axes[-1, c_idx].set_xlabel("Distance (m)", fontsize=11)

    # -----------------------------
    # Figure title
    # -----------------------------
    if len(freqs_hz) == 1:
        freq_ghz = freqs_hz[0] / 1e9
        fig.suptitle(f"{freq_ghz:g} GHz RCS Profiles ({unit_str})", fontsize=14)
    else:
        fig.suptitle(f"RCS Profiles ({unit_str})", fontsize=14)

    # -----------------------------
    # Legend
    # -----------------------------
    if legend and len(legend_handles) > 0:
        fig.legend(
            legend_handles,
            legend_labels,
            title="Subject",
            fontsize=9,
            title_fontsize=10,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.1),
            ncol=len(legend_labels),
            frameon=True,
        )

    plt.tight_layout(rect=[0.04, 0.03, 0.98, 0.96])
    plt.show()
plot_rcs_profile_grid(
    df_all, freqs_hz=2.4e9, 
    label_mode="name", number_prefix="Subject ",
    plot_dbsm=False)
## 24 GHz RCS Profiles
plot_rcs_profile_grid(
    df_all, freqs_hz=24e9, 
    label_mode="name", number_prefix="Subject ",
    plot_dbsm=False)
## Single Segment Profiles
import numpy as np
import matplotlib.pyplot as plt

def plot_rcs_freq_by_pol_grid(
    df,
    freqs_hz=(2.4e9, 24e9),      # one or more frequencies
    segment_type="single",       # "single" or "multi"
    subjects=None,
    plot_dbsm=False,
    sigma_col="sigma_human",
    subject_col="subject",
    dist_col="dist_m",
    freq_col="freq_hz",
    segtype_col="segment_type",
    pol_col="pol_tx",
    figsize=None,
    jitter=0.012,
    marker_size=42,
    show_mean=True,
    sharey=False,
    label_mode="name",           # "name" or "number"
    number_prefix="Subject ",
    legend=True,
):
    """
    Plot all subjects with:
        rows = frequency
        cols = polarization

    Example layout for freqs_hz=(2.4e9, 24e9):
        [2.4 GHz VV] [2.4 GHz HH]
        [24  GHz VV] [24  GHz HH]
    """

    # -----------------------------
    # Allow single frequency input
    # -----------------------------
    if np.isscalar(freqs_hz):
        freqs_hz = (float(freqs_hz),)
    else:
        freqs_hz = tuple(freqs_hz)

    # -----------------------------
    # Normalize/filter base DataFrame
    # -----------------------------
    df_plot = df.copy()

    pol_map = {
        "v": "V",
        "vertical": "V",
        "h": "H",
        "horizontal": "H",
    }

    def normalize_pol(val):
        sval = str(val).strip().lower()
        return pol_map.get(sval, str(val).strip().upper())

    df_plot[pol_col] = df_plot[pol_col].apply(normalize_pol)

    if subjects is not None:
        df_plot = df_plot[df_plot[subject_col].isin(subjects)].copy()

    df_plot = df_plot[
        df_plot[segtype_col].astype(str).str.lower() == str(segment_type).lower()
    ].copy()

    if df_plot.empty:
        print(f"No data found for segment_type='{segment_type}'.")
        return

    # -----------------------------
    # Unit conversion
    # -----------------------------
    if plot_dbsm:
        n_bad = (df_plot[sigma_col] <= 0).sum()
        if n_bad > 0:
            print(f"Skipping {n_bad} non-positive sigma values for dBsm conversion.")
        df_plot = df_plot[df_plot[sigma_col] > 0].copy()
        df_plot["sigma_plot"] = 10 * np.log10(df_plot[sigma_col])
        y_label = r"$\sigma_{\mathrm{human}}$ (dBsm)"
        unit_str = "dBsm"
    else:
        df_plot["sigma_plot"] = df_plot[sigma_col]
        y_label = r"$\sigma_{\mathrm{human}}$ (m$^2$)"
        unit_str = "m$^2$"

    if df_plot.empty:
        print("No valid data left to plot after filtering.")
        return

    # -----------------------------
    # Subject ordering / markers
    # -----------------------------
    if subjects is None:
        subjects_use = sorted(df_plot[subject_col].dropna().unique())
    else:
        subjects_use = [s for s in subjects if s in df_plot[subject_col].unique()]

    if len(subjects_use) == 0:
        print("No matching subjects found.")
        return

    marker_list = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "*", "h", "8"]
    subject_marker_map = {
        subj: marker_list[i % len(marker_list)]
        for i, subj in enumerate(subjects_use)
    }

    n_subj = len(subjects_use)
    if n_subj == 1:
        subj_offsets = {subjects_use[0]: 0.0}
    else:
        offsets = np.linspace(-jitter, jitter, n_subj)
        subj_offsets = {subj: offsets[i] for i, subj in enumerate(subjects_use)}

    pol_order = ["V", "H"]
    pol_titles = {
        "V": "VV Polarization",
        "H": "HH Polarization",
    }
    pol_color_map = {
        "V": "tab:blue",
        "H": "tab:orange",
    }

    # -----------------------------
    # Figure layout
    # -----------------------------
    nrows = len(freqs_hz)
    ncols = len(pol_order)

    if figsize is None:
        figsize = (8.2, 3.1 * nrows)

    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=figsize,
        sharex=True,
        sharey=sharey,
        constrained_layout=False
    )

    # Force 2D indexing
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1:
        axes = axes[np.newaxis, :]
    elif ncols == 1:
        axes = axes[:, np.newaxis]

    # Column titles
    for c_idx, pol in enumerate(pol_order):
        axes[0, c_idx].set_title(pol_titles[pol], fontsize=12, pad=10)

    legend_handles = []
    legend_labels = []

    # -----------------------------
    # Plot panels
    # -----------------------------
    for r_idx, freq_hz in enumerate(freqs_hz):
        freq_ghz = freq_hz / 1e9

        for c_idx, pol in enumerate(pol_order):
            ax = axes[r_idx, c_idx]

            df_panel = df_plot[
                (df_plot[freq_col] == freq_hz) &
                (df_plot[pol_col] == pol)
            ].copy()

            if df_panel.empty:
                ax.text(
                    0.5, 0.5, "No data",
                    transform=ax.transAxes,
                    ha="center", va="center", fontsize=10
                )
                ax.grid(True, linestyle="--", alpha=0.35)
                if c_idx == 0:
                    ax.set_ylabel(y_label, fontsize=10)
                    ax.text(
                        -0.28, 0.5,
                        f"{freq_ghz:g} GHz",
                        transform=ax.transAxes,
                        rotation=90,
                        ha="center", va="center",
                        fontsize=11
                    )
                continue

            for subj_idx, subj in enumerate(subjects_use, start=1):
                df_subj = df_panel[df_panel[subject_col] == subj].copy()
                if df_subj.empty:
                    continue

                marker = subject_marker_map[subj]
                color = pol_color_map[pol]
                offset = subj_offsets[subj]

                if label_mode.lower() == "name":
                    label = str(subj)
                elif label_mode.lower() == "number":
                    label = f"{number_prefix}{subj_idx}"
                else:
                    raise ValueError("label_mode must be 'name' or 'number'")

                for dist in sorted(df_subj[dist_col].dropna().unique()):
                    df_dist = df_subj[df_subj[dist_col] == dist]
                    y = df_dist["sigma_plot"].dropna().to_numpy()
                    if len(y) == 0:
                        continue

                    local_jitter = (
                        np.arange(len(y)) - (len(y) - 1) / 2.0
                    ) * (jitter * 0.35)

                    x = np.full(len(y), float(dist)) + offset + local_jitter

                    sc = ax.scatter(
                        x, y,
                        s=marker_size,
                        marker=marker,
                        color=color,
                        edgecolors="black",
                        linewidths=0.5,
                        alpha=0.9,
                        zorder=3,
                    )

                    if label not in legend_labels:
                        legend_handles.append(sc)
                        legend_labels.append(label)

                if show_mean:
                    mean_df = (
                        df_subj.groupby(dist_col, as_index=False)["sigma_plot"]
                        .mean()
                        .sort_values(dist_col)
                    )
                    if len(mean_df) > 0:
                        ax.plot(
                            mean_df[dist_col].to_numpy() + offset,
                            mean_df["sigma_plot"].to_numpy(),
                            linestyle="--",
                            color=color,
                            linewidth=1.0,
                            alpha=0.9,
                            zorder=2,
                        )

            ax.grid(True, linestyle="--", alpha=0.35)

            if c_idx == 0:
                ax.set_ylabel(y_label, fontsize=10)
                ax.text(
                    -0.28, 0.5,
                    f"{freq_ghz:g} GHz",
                    transform=ax.transAxes,
                    rotation=90,
                    ha="center", va="center",
                    fontsize=11
                )

    # -----------------------------
    # X-axis formatting
    # -----------------------------
    dists = sorted(df_plot[dist_col].dropna().unique())
    if len(dists) > 0:
        for ax in axes.flatten():
            ax.set_xticks(dists)
            ax.set_xlim(min(dists) - 0.08, max(dists) + 0.08)

    for c_idx in range(ncols):
        axes[-1, c_idx].set_xlabel("Distance (m)", fontsize=11)

    # -----------------------------
    # Figure title
    # -----------------------------
    if len(freqs_hz) == 1:
        fig.suptitle(
            f"{freqs_hz[0]/1e9:g} GHz RCS Profiles ({segment_type.capitalize()} Segments, {unit_str})",
            fontsize=14
        )
    else:
        fig.suptitle(
            f"RCS Profiles ({segment_type.capitalize()} Segments, {unit_str})",
            fontsize=14
        )

    # -----------------------------
    # Legend
    # -----------------------------
    if legend and len(legend_handles) > 0:
        fig.legend(
            legend_handles,
            legend_labels,
            title="Subject",
            fontsize=9,
            title_fontsize=10,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.1),
            ncol=len(legend_labels),
            frameon=True,
        )

    plt.tight_layout(rect=[0.04, 0.03, 0.98, 0.94])
    plt.show()
plot_rcs_freq_by_pol_grid(
    df_all,
    freqs_hz=(2.4e9, 24e9),
    segment_type="single",
    label_mode="name",
    number_prefix="Subject ",
)
## Multi Segment Profiles
plot_rcs_freq_by_pol_grid(
    df_all,
    freqs_hz=(2.4e9, 24e9),
    segment_type="multi",
    label_mode="name",
    number_prefix="Subject ",
)
## RCS Query
sub = "run"
view_freq = 2.4e9
plot_subject_rcs_profile_2x2(
    df_all,
    subject=sub,
    freq_hz=view_freq,
    plot_dbsm=True,
)
df_pol = compute_pol_difference_table(df_all)
display(
    df_pol[
        (df_pol["subject"] == sub)
    ]
    .sort_values(["segment_type", "freq_hz",  "dist_m"])[
        ["subject", "freq_hz", "segment_type", "dist_m", "sigma_V", "sigma_H", "V_over_H_linear", "delta_V_minus_H_dB"]
    ]
)
## Polarization Heatmap
df_pol_ratio = compute_polarization_ratio_table(df_all)

plot_polarization_preference_heatmap(
    df_pol_ratio,
    freq_hz=2.4e9,
    segment_type="single",
    value_col="V_minus_H_dB",
)
plot_polarization_preference_heatmap(
    df_pol_ratio,
    freq_hz=24e9,
    segment_type="single",
    value_col="V_minus_H_dB",
)
plot_polarization_preference_heatmap(
    df_pol_ratio,
    freq_hz=2.4e9,
    segment_type="multi",
    value_col="V_minus_H_dB",
)
plot_polarization_preference_heatmap(
    df_pol_ratio,
    freq_hz=24e9,
    segment_type="multi",
    value_col="V_minus_H_dB",
)
import matplotlib.pyplot as plt

vals = df_pol_ratio["V_minus_H_dB"].dropna()

plt.figure(figsize=(6, 4))
plt.hist(vals, bins=20)
plt.xlabel("V - H (dB)")
plt.ylabel("Count")
plt.title("Histogram of polarization difference")
plt.grid(True, alpha=0.3)
plt.show()
print(df_pol_ratio["V_minus_H_dB"].describe())
bins = pd.cut(df_pol_ratio["V_minus_H_dB"], bins=10)
print(bins.value_counts().sort_index())



 