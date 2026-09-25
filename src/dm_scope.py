#!/usr/bin/env python3
"""Live browser constellation for the narrowband modulation lab.

On the receiver node, run:
    bokeh serve dm_scope.py --port 5006 --args --freq 2400e6
For an N210 add: --args addr=192.168.10.2 --subdev A:0 --gain 30
"""

import argparse
import sys

import numpy as np
from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, Div, Select, Slider
from bokeh.plotting import figure

import dm_common as dm
import dm_rx

ap = argparse.ArgumentParser()
ap.add_argument("--freq", type=float, default=2400e6)
ap.add_argument("--args", default="type=b200")
ap.add_argument("--subdev", default="A:A")
ap.add_argument("--antenna", default="RX2")
ap.add_argument("--gain", type=float, default=40)
a = ap.parse_args(sys.argv[1:])

receiver = dm_rx.get_receiver(freq=a.freq, args=a.args, subdev=a.subdev,
                               antenna=a.antenna, gain=a.gain)
doc = curdoc()
doc.title = "Digital modulation scope"

levels = Select(title="Modulation (match the transmitter)",
                options=[("2", "BPSK"), ("4", "QPSK"), ("16", "16-QAM")], value="4")
gain = Slider(title="RX gain (dB)", start=0, end=76 if a.subdev == "A:A" else 31,
              step=1, value=a.gain)
readout = Div(text="Waiting for a frame...")
status = Div(text="")
points = ColumnDataSource(dict(i=[], q=[]))
ideal = ColumnDataSource(dict(i=[], q=[]))

plot = figure(title="Received symbols (after channel and frequency correction)",
              width=650, height=600, x_range=(-1.7, 1.7), y_range=(-1.7, 1.7),
              x_axis_label="In-phase (I)", y_axis_label="Quadrature (Q)",
              tools="pan,box_zoom,wheel_zoom,reset,save")
plot.scatter("i", "q", source=points, size=3, alpha=0.35, color="#2673bf")
plot.scatter("i", "q", source=ideal, size=15, marker="cross", color="red", line_width=2)
plot.match_aspect = True
plot.grid.grid_line_alpha = 0.3


def change_levels(attr, old, new):
    receiver.set_levels(int(new))
    points.data = dict(i=[], q=[])
    ideal.data = dict(i=[], q=[])


def change_gain(attr, old, new):
    receiver.set_gain(new)


levels.on_change("value", change_levels)
gain.on_change("value_throttled", change_gain)
doc.add_root(column(Div(text="<h2>Live narrowband constellation</h2>"),
                    row(column(levels, gain, status, width=280),
                        column(readout, plot)), sizing_mode="stretch_width"))
last_version = -1


def tick():
    global last_version
    if receiver.version == last_version:
        return
    last_version = receiver.version
    status.text = receiver.status
    result = receiver.latest
    if result is None:
        readout.text = "Waiting for a %s transmitter at %.3f MHz." % (
            {"2": "BPSK", "4": "QPSK", "16": "16-QAM"}[levels.value], a.freq / 1e6)
        points.data = dict(i=[], q=[])
        return
    symbols = result["symbols"]
    # Display one short frame, with no accumulating stale points.
    points.data = dict(i=symbols.real.tolist(), q=symbols.imag.tolist())
    reference = result["points"]
    ideal.data = dict(i=reference.real.tolist(), q=reference.imag.tolist())
    readout.text = ("<b>EVM</b> %.1f%% &nbsp; <b>SNR from error</b> %.1f dB &nbsp; "
                    "<b>Bit errors</b> %d / %d &nbsp; <b>CFO</b> %+.0f Hz" %
                    (100 * result["evm"], result["snr_db"], result["bit_errors"],
                     result["bits"], result["cfo_hz"]))


doc.add_periodic_callback(tick, 300)
