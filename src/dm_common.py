"""Known narrowband waveform and frame measurements shared by TX and RX."""

import numpy as np
from scipy.signal import correlate, fftconvolve, find_peaks

SYMBOL_RATE = 250_000
SAMPLES_PER_SYMBOL = 8
SAMPLE_RATE = SYMBOL_RATE * SAMPLES_PER_SYMBOL
FRAME_SYMBOLS = 512
TRAINING_SYMBOLS = 96
SPAN_SYMBOLS = 10


def constellation(levels):
    if levels == 2:
        return np.array([-1, 1], np.complex64)
    if levels == 4:
        return np.array([-1-1j, -1+1j, 1-1j, 1+1j], np.complex64) / np.sqrt(2)
    if levels == 16:
        return np.array([x + 1j*y for x in (-3, -1, 1, 3)
                         for y in (-3, -1, 1, 3)], np.complex64) / np.sqrt(10)
    raise ValueError("levels must be 2, 4, or 16")


def rrc_taps(beta=0.35):
    """Unit-DC-gain root-raised-cosine pulse with an integer symbol span."""
    t = np.arange(-SPAN_SYMBOLS * SAMPLES_PER_SYMBOL // 2,
                  SPAN_SYMBOLS * SAMPLES_PER_SYMBOL // 2 + 1) / SAMPLES_PER_SYMBOL
    h = np.empty_like(t, dtype=float)
    for i, v in enumerate(t):
        if abs(v) < 1e-10:
            h[i] = 1 + beta * (4 / np.pi - 1)
        elif abs(abs(4 * beta * v) - 1) < 1e-10:
            h[i] = beta / np.sqrt(2) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) +
                (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * v * (1 - beta)) +
                    4 * beta * v * np.cos(np.pi * v * (1 + beta))) / (
                    np.pi * v * (1 - (4 * beta * v) ** 2))
    return (h / h.sum()).astype(np.float32)


def circular_filter(samples, taps):
    n = len(samples)
    return np.convolve(np.tile(samples, 3), taps, mode="full")[n:2*n]


def make_frame(levels, amplitude=0.2):
    points = constellation(levels)
    indices = np.random.RandomState(20260924).randint(0, levels, FRAME_SYMBOLS)
    symbols = points[indices]
    up = np.zeros(FRAME_SYMBOLS * SAMPLES_PER_SYMBOL, dtype=np.complex64)
    up[::SAMPLES_PER_SYMBOL] = symbols
    taps = rrc_taps()
    waveform = circular_filter(up, taps)
    waveform *= amplitude / np.max(np.abs(waveform))
    return indices, symbols, waveform.astype(np.complex64)


def measure(samples, levels, amplitude=0.2):
    """Find a complete known frame and return corrected symbols, EVM and errors.

    The entire repeated frame is known, so clock phase, frequency offset, and
    complex channel gain can be estimated without guessing transmitted symbols.
    """
    indices, symbols, ref = make_frame(levels, amplitude)
    taps = rrc_taps()
    length = len(ref)
    x = np.asarray(samples, np.complex64)
    start_training = 16 * SAMPLES_PER_SYMBOL
    template = ref[start_training:TRAINING_SYMBOLS * SAMPLES_PER_SYMBOL]
    if len(x) < 2 * length:
        return None
    correlation = np.abs(correlate(x, template, mode="valid", method="fft"))
    peaks, _ = find_peaks(correlation, distance=length // 2)
    ref_energy = np.vdot(template, template).real
    energy = fftconvolve(np.abs(x) ** 2, np.ones(len(template)), "valid")
    # Start with the most recent complete frame, not the strongest old frame.
    for peak in peaks[::-1]:
        first = peak - start_training
        if first < 0 or first + length > len(x):
            continue
        score = correlation[peak] / np.sqrt(ref_energy * energy[peak] + 1e-20)
        if score < 0.22:
            continue
        frame = x[first:first + length]
        # Each block sees the same known waveform. Its complex correlation
        # gives one channel-phase observation; the slope is the residual CFO.
        block = 128
        ref_blocks = ref.reshape(-1, block)
        rx_blocks = frame.reshape(-1, block)
        phases = np.sum(rx_blocks * np.conj(ref_blocks), axis=1)
        phase_step = np.angle(np.sum(phases[1:] * np.conj(phases[:-1]))) / block
        corrected = frame * np.exp(-1j * phase_step * np.arange(length))
        # Matched-filter both the received waveform and its known reference.
        received_m = np.convolve(corrected, taps, mode="same")
        centers = (np.arange(TRAINING_SYMBOLS, FRAME_SYMBOLS - SPAN_SYMBOLS) *
                   SAMPLES_PER_SYMBOL + (len(taps) - 1) // 2)
        # Choose the sample phase with the least error relative to known data.
        candidate = None
        for offset in range(-SAMPLES_PER_SYMBOL // 2, SAMPLES_PER_SYMBOL // 2 + 1):
            positions = centers + offset
            observed = received_m[positions]
            target = symbols[TRAINING_SYMBOLS:FRAME_SYMBOLS - SPAN_SYMBOLS]
            gain = np.vdot(target, observed) / np.vdot(target, target)
            if abs(gain) < 1e-10:
                continue
            equalized = observed / gain
            error = np.mean(np.abs(equalized - target) ** 2)
            if candidate is None or error < candidate[0]:
                candidate = (error, equalized, target, indices[TRAINING_SYMBOLS:FRAME_SYMBOLS - SPAN_SYMBOLS])
        if candidate is None:
            continue
        power, equalized, target, sent = candidate
        points = constellation(levels)
        decoded = np.argmin(abs(equalized[:, None] - points[None, :]), axis=1)
        bit_errors = sum((int(a) ^ int(b)).bit_count() for a, b in zip(sent, decoded))
        return dict(symbols=equalized, points=points, evm=np.sqrt(power),
                    snr_db=-10 * np.log10(power + 1e-20),
                    symbol_errors=int(np.count_nonzero(decoded != sent)),
                    bit_errors=bit_errors, bits=len(sent) * int(np.log2(levels)),
                    cfo_hz=phase_step * SAMPLE_RATE / (2 * np.pi),
                    score=float(score))
    return None
