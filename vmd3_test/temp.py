BINARY_FILEPATH = (
    "/home/shaylon/repos/ALiSM_Python_copy/vmd3_test/data/radc/2026-05-26/"
    "plate_7p5m_1p6mm_0p2hz_rset1.bin"
)

with open(BINARY_FILEPATH, 'rb') as f:
    raw = f.read()

idx = raw.find(b'RADC')
payload = raw[idx+8 : idx+8+131072]

q_val = int.from_bytes(payload[0:2], byteorder='little', signed=True)
i_val = int.from_bytes(payload[2:4], byteorder='little', signed=True)

print(f'First Q = {q_val}, First I = {i_val}, complex = {i_val} + {q_val}j')

import numpy as np

# Reuse the same payload from before
raw_arr = np.frombuffer(payload, dtype='<i2')
raw_arr = raw_arr.reshape(64, 4, 256)
q_values = raw_arr[:, :, 0::2]
i_values = raw_arr[:, :, 1::2]
complex_data = i_values.astype(np.float64) + 1j * q_values.astype(np.float64)
cube = np.transpose(complex_data, (2, 0, 1))

print(f'cube[0,0,0] = {cube[0,0,0]}')
print(f'cube[1,0,0] = {cube[1,0,0]}')
print(f'cube[0,1,0] = {cube[0,1,0]}')
print(f'cube[0,0,1] = {cube[0,0,1]}')

fft_test = np.fft.fft(cube, axis=0)
print(f'fft[29,0,0] = {fft_test[29,0,0]}')
print(f'mean at bin 30 = {np.mean(fft_test[29, :, :])}')