#!/usr/bin/env python3
"""Transmit the repeated, known narrowband frame used by the live scope."""

import argparse
import signal
import time

from gnuradio import blocks, gr, uhd

import dm_common as dm


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-f", "--freq", type=float, default=2400e6)
    p.add_argument("-p", "--levels", type=int, choices=(2, 4, 16), default=4)
    p.add_argument("--tx-gain", type=float, default=79.0)
    p.add_argument("--amplitude", type=float, default=0.2)
    p.add_argument("--args", default="type=b200", help="UHD device args; N210: addr=192.168.10.2")
    p.add_argument("--subdev", default="A:A", help="N210: A:0")
    p.add_argument("--antenna", default="TX/RX")
    p.add_argument("--seconds", type=float, default=0,
                   help="stop after this many seconds; 0 runs until Ctrl-C")
    a = p.parse_args()

    _, _, waveform = dm.make_frame(a.levels, a.amplitude)
    tb = gr.top_block("Digital modulation transmitter")
    source = blocks.vector_source_c(waveform.tolist(), True)
    radio = uhd.usrp_sink(a.args, uhd.stream_args(cpu_format="fc32", channels=[0]))
    radio.set_subdev_spec(a.subdev, 0)
    radio.set_samp_rate(dm.SAMPLE_RATE)
    if radio.get_samp_rate() != dm.SAMPLE_RATE:
        raise RuntimeError("Radio did not accept %d S/s" % dm.SAMPLE_RATE)
    radio.set_center_freq(a.freq, 0)
    radio.set_gain(a.tx_gain, 0)
    radio.set_antenna(a.antenna, 0)
    tb.connect(source, radio)
    print("TX %d-point constellation, %d symbols/s, %d S/s, gain %g dB" %
          (a.levels, dm.SYMBOL_RATE, dm.SAMPLE_RATE, a.tx_gain), flush=True)
    tb.start()
    try:
        if a.seconds:
            time.sleep(a.seconds)
        else:
            signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        tb.stop()
        tb.wait()


if __name__ == "__main__":
    main()
