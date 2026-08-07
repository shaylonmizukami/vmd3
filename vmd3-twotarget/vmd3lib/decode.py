"""
decode.py — Read and decode VMD3 RADC binary files (2D mode).

Two responsibilities:
  get_frames()      : pull valid RADC frame payloads out of a .bin file
  decode_radc_2d()  : turn one payload into a complex (samples, chirps,
                      channels) cube

RADC-only, 2D-only. No plotting, no side effects on import.
"""

import numpy as np

from vmd3lib.config import (
    RADC_2D_FRAME_LEN, N_SAMPLES, N_CHIRPS, N_CHANNELS, HEADER_RADC,
)


def get_frames(filepath, header=HEADER_RADC):
    """
    Read a .bin file and return a list of valid RADC frame payloads.

    Scans for every occurrence of the header, reads the 4-byte
    little-endian payload length that follows, keeps only payloads whose
    length matches a 2D RADC frame, and rejects any payload that happens
    to contain the header sequence (guards against a false header match
    inside frame data).
    """
    with open(filepath, 'rb') as f:
        raw = f.read()

    frames = []
    start = 0
    while True:
        idx = raw.find(header, start)
        if idx == -1:
            break

        # Need at least header + 4 length bytes to read a length.
        if idx + 8 > len(raw):
            break
        payload_len = int.from_bytes(
            raw[idx + 4:idx + 8], byteorder='little', signed=False
        )

        if payload_len == RADC_2D_FRAME_LEN:
            p_start = idx + 8
            p_end = p_start + payload_len
            if p_end <= len(raw):
                payload = raw[p_start:p_end]
                if header not in payload:
                    frames.append(payload)

        start = idx + 1

    return frames


def decode_radc_2d(frame):
    """
    Decode one 2D-mode RADC payload into a complex cube.

    Output shape: (samples, chirps, channels) = (128, 64, 4), complex.

    Byte layout (per 2048-byte sweep, 64 sweeps):
      4 channel blocks of 512 bytes; within a block, int16 little-endian
      with Q at even offsets (0, 4, 8, ...) and I at odd (2, 6, 10, ...).
      Complex value is I + jQ.
    """
    if len(frame) != RADC_2D_FRAME_LEN:
        raise ValueError(
            f'Invalid 2D RADC frame length: {len(frame)} '
            f'(expected {RADC_2D_FRAME_LEN})'
        )

    raw = np.frombuffer(frame, dtype='<i2')       # 65536 int16
    raw = raw.reshape(N_CHIRPS, N_CHANNELS, 2 * N_SAMPLES)  # (64, 4, 256)

    q = raw[:, :, 0::2]   # Q at even int16 positions
    i = raw[:, :, 1::2]   # I at odd int16 positions

    cplx = i.astype(np.float64) + 1j * q.astype(np.float64)
    # currently (chirps, channels, samples) -> want (samples, chirps, channels)
    cube = np.transpose(cplx, (2, 0, 1))
    return cube