import numpy as np
import matplotlib.pyplot as plt

# --- Design values (1 kOhm version, +/-12 V output swing) ---
R_i = 1e3           # ohms
R_f = 133.33e3      # ohms
C_i = 6.366e-6      # farads
C_f = 397.9e-12     # farads

# --- Derived quantities ---
A_mid  = R_f / R_i
f_c1   = 1.0 / (2 * np.pi * R_i * C_i)
f_c2   = 1.0 / (2 * np.pi * R_f * C_f)
A_dB   = 20 * np.log10(A_mid)

# --- Transfer function: inverting HP x LP ---
f = np.logspace(0, 5, 4000)
s = 1j * 2 * np.pi * f
H = -(R_f / R_i) * (s * R_i * C_i) / ((1 + s * R_i * C_i) * (1 + s * R_f * C_f))
mag_dB = 20 * np.log10(np.abs(H))

# --- Plot ---
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.semilogx(f, mag_dB, lw=2)
ax.axhline(A_dB - 3, ls=':', lw=1, color='gray', label='-3dB')
ax.axvline(f_c1, ls='--', lw=1, color='gray')
ax.axvline(f_c2, ls='--', lw=1, color='gray')

ax.text(f_c1, 2, f'{f_c1:.1f} Hz', rotation=90, va='bottom', ha='right', fontsize=8)
ax.text(f_c2, 2, f'{f_c2/1e3:.2f} kHz', rotation=90, va='bottom', ha='right', fontsize=8)

ax.set_xlabel('f (Hz)')
ax.set_ylabel('Gain (dB)')
ax.set_ylim(0, A_dB + 5)
ax.grid(True, which='both', ls=':', lw=0.5)
ax.legend(loc='lower center', fontsize=8)
plt.tight_layout()
plt.show()

# --- Summary ---
print(f'R_i    = {R_i/1e3:.3f} kOhm')
print(f'R_f    = {R_f/1e3:.3f} kOhm')
print(f'C_i    = {C_i*1e6:.4f} uF')
print(f'C_f    = {C_f*1e12:.2f} pF')
print(f'A_mid  = {A_mid:.2f}  ({A_dB:.2f} dB)')
print(f'f_c1   = {f_c1:.2f} Hz')
print(f'f_c2   = {f_c2:.2f} Hz')