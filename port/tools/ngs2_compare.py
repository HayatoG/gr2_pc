#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compares two NGS2 mixes recorded as float WAV (TLG_NGS2_TRACE_WAV with the console module,
TLG_NGS2_WAV with the built-in mixer): per-channel level, how much of the time each channel is
active, and the spectral balance, over the whole file or a window.

    ngs2_compare.py native.wav builtin.wav [--start S] [--seconds N]

The two runs are never sample-aligned (different sessions), so this compares statistics, not
waveforms. Large level differences point at volume/matrix bugs; a channel silent in one mix and
not in the other at routing; a shifted spectrum at pitch/resampling or missing filters.
"""
import argparse
import struct
import sys

import numpy as np

NAMES = ['FL', 'FR', 'FC', 'LFE', 'SL', 'SR', 'BL', 'BR']


def read_wav(path, start, seconds):
    with open(path, 'rb') as f:
        if f.read(4) != b'RIFF':
            sys.exit(f'{path}: not a WAV file')
        f.read(8)
        channels = rate = 0
        while True:
            head = f.read(8)
            if len(head) < 8:
                sys.exit(f'{path}: no data chunk')
            tag, size = head[:4], struct.unpack('<I', head[4:])[0]
            if tag == b'fmt ':
                fmt = f.read(size)
                kind, channels, rate = struct.unpack('<HHI', fmt[:8])
                if kind != 3:
                    sys.exit(f'{path}: expected float samples')
            elif tag == b'data':
                f.seek(int(start * rate) * channels * 4, 1)
                count = int(seconds * rate) * channels if seconds else -1
                data = np.fromfile(f, dtype='<f4', count=count)
                frames = len(data) // channels
                return data[:frames * channels].reshape(frames, channels), rate
            else:
                f.seek(size, 1)


def describe(name, x, rate):
    print(f'{name}: {len(x) / rate:.1f} s, {x.shape[1]} channels')
    window = rate // 10
    blocks = len(x) // window
    for c in range(x.shape[1]):
        ch = x[:blocks * window, c]
        rms = np.sqrt(np.mean(ch * ch)) if len(ch) else 0.0
        peak = np.max(np.abs(ch)) if len(ch) else 0.0
        active = np.mean(np.sqrt(np.mean(ch.reshape(blocks, window) ** 2, axis=1)) > 1e-3) if blocks else 0.0
        spectrum = np.abs(np.fft.rfft(ch[:rate * 8])) if len(ch) >= rate else None
        centroid = 0.0
        if spectrum is not None and spectrum.sum() > 0:
            freqs = np.fft.rfftfreq(min(len(ch), rate * 8), 1.0 / rate)
            centroid = float((freqs * spectrum).sum() / spectrum.sum())
        label = NAMES[c] if c < len(NAMES) else str(c)
        print(f'  {label:>3}: rms {20 * np.log10(rms + 1e-12):6.1f} dB  peak {peak:5.2f}  active {active * 100:5.1f}%  '
              f'centroid {centroid:6.0f} Hz')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('files', nargs='+')
    parser.add_argument('--start', type=float, default=0.0, help='seconds to skip')
    parser.add_argument('--seconds', type=float, default=0.0, help='seconds to read (0 = all)')
    args = parser.parse_args()
    for path in args.files:
        x, rate = read_wav(path, args.start, args.seconds)
        describe(path, x, rate)


if __name__ == '__main__':
    main()
