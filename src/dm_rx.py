"""One shared live UHD receiver for every browser session of dm_scope.py."""

import argparse
import threading
import time

import numpy as np
from gnuradio import gr, uhd

import dm_common as dm


class Tap(gr.sync_block):
    def __init__(self, receiver):
        gr.sync_block.__init__(self, name="IQ tap", in_sig=[np.complex64], out_sig=[])
        self.receiver = receiver

    def work(self, input_items, output_items):
        x = input_items[0]
        self.receiver.push(x)
        return len(x)


class Receiver:
    def __init__(self, freq=2400e6, gain=40, args="type=b200", subdev="A:A", antenna="RX2"):
        self.lock = threading.Lock()
        self.levels = 4
        self.gain = gain
        self.status = "starting"
        self.version = 0
        self.latest = None
        self.ring = np.zeros(8 * dm.FRAME_SYMBOLS * dm.SAMPLES_PER_SYMBOL, np.complex64)
        self.end = 0
        self.tb = gr.top_block("Digital modulation live receiver")
        self.radio = uhd.usrp_source(args, uhd.stream_args(cpu_format="fc32", channels=[0]))
        self.radio.set_subdev_spec(subdev, 0)
        self.radio.set_samp_rate(dm.SAMPLE_RATE)
        if self.radio.get_samp_rate() != dm.SAMPLE_RATE:
            raise RuntimeError("Radio did not accept %d S/s" % dm.SAMPLE_RATE)
        self.radio.set_center_freq(freq, 0)
        self.radio.set_gain(gain, 0)
        self.radio.set_antenna(antenna, 0)
        self.tap = Tap(self)
        self.tb.connect(self.radio, self.tap)
        self.tb.start()
        self.status = "searching for transmitter"
        threading.Thread(target=self._process, daemon=True).start()

    def push(self, x):
        with self.lock:
            n = min(len(x), len(self.ring))
            start = self.end % len(self.ring)
            if n != len(x):
                x = x[-n:]
            split = min(n, len(self.ring) - start)
            self.ring[start:start + split] = x[:split]
            self.ring[:n - split] = x[split:]
            self.end += n

    def set_levels(self, levels):
        with self.lock:
            self.levels = int(levels)
            self.end = 0
            self.latest = None
            self.status = "searching for %d-point transmitter" % levels

    def set_gain(self, gain):
        self.radio.set_gain(float(gain), 0)
        self.gain = float(gain)

    def _process(self):
        length = len(self.ring)
        while True:
            try:
                with self.lock:
                    end = self.end
                    levels = self.levels
                    if end >= length:
                        pos = end % length
                        samples = np.concatenate((self.ring[pos:], self.ring[:pos]))
                    else:
                        samples = None
                if samples is not None:
                    result = dm.measure(samples, levels)
                    with self.lock:
                        if self.levels == levels:
                            self.latest = result
                            self.status = "ok" if result is not None else "searching for %d-point transmitter" % levels
                            self.version += 1
            except Exception as exc:
                self.status = "receiver error: %s" % exc
            time.sleep(0.25)

    def stop(self):
        self.tb.stop()
        self.tb.wait()


_receiver = None


def get_receiver(**kwargs):
    global _receiver
    if _receiver is None:
        _receiver = Receiver(**kwargs)
    return _receiver


def main():
    parser = argparse.ArgumentParser(description="Capture and measure a known frame")
    parser.add_argument("-f", "--freq", type=float, default=2400e6)
    parser.add_argument("-p", "--levels", type=int, choices=(2, 4, 16), default=4)
    parser.add_argument("--gain", type=float, default=40)
    parser.add_argument("--args", default="type=b200",
                        help="UHD device args; N210: addr=192.168.10.2")
    parser.add_argument("--subdev", default="A:A", help="N210: A:0")
    parser.add_argument("--antenna", default="RX2")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--out", required=True, help="output .npz file")
    args = parser.parse_args()

    receiver = Receiver(freq=args.freq, gain=args.gain, args=args.args,
                        subdev=args.subdev, antenna=args.antenna)
    receiver.set_levels(args.levels)
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.25)
            if receiver.latest is not None:
                result = receiver.latest
                np.savez(args.out, mod={2: "BPSK", 4: "QPSK", 16: "16-QAM"}[args.levels],
                         snr_db=result["snr_db"], evm=result["evm"],
                         symbols=result["symbols"], points=result["points"],
                         gain=args.gain)
                print("saved %s: EVM %.1f%%, SNR %.1f dB, bit errors %d/%d" %
                      (args.out, 100 * result["evm"], result["snr_db"],
                       result["bit_errors"], result["bits"]))
                return
        raise RuntimeError("no complete known frame found (%s)" % receiver.status)
    finally:
        receiver.stop()


if __name__ == "__main__":
    main()
