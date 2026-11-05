# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************
""" 
This example shows the visualisation of an intensity map on Linux I2C.
Measurements are performed and a pixel map is shown either with pyplot or a Flask frontend.
"""
import __init__ 
import argparse
import threading
import time

from __init__ import HEX_FILE
from tmf8829_conv import *
from tmf8829_application import Tmf8829Application
from tmf8829_application_defines import tmf8829RefSpadFrame
from utilities.tmf8829_visualisation import Tmf8829PlotPixelMap

###################################################################################
## User Config
###################################################################################
_fpMode = Tmf8829Application.FP_MODE_32x32
_use_iterations = 500
_use_period = 100
_frontend = "pyplot"            # "pyplot" or "flask"
_flask_host = "127.0.0.1"
_flask_port = 8080
###################################################################################
## Example for the Histogram Visualisation 
###################################################################################
def _read_pixel_map_data(app):
    resultFrame, _, refFrame = app.readMeasurementFrames(timeout=1.0)
    if len(resultFrame) == 0 or len(refFrame) == 0:
        return None

    pixelResults = app.getFullPixelResult(resultFrame)
    ref_frame = tmf8829RefSpadFrame.from_buffer_copy(refFrame[0])

    fp_noise = []
    for row in pixelResults:
        fp_noise.append([0 if pixel["noise"] is None else int(pixel["noise"]) for pixel in row])

    ref_t0 = [
        [int(ref_frame.sum[0][0]), int(ref_frame.sum[0][1])],
        [int(ref_frame.sum[0][2]), int(ref_frame.sum[0][3])],
    ]
    ref_t1 = [
        [int(ref_frame.sum[1][0]), int(ref_frame.sum[1][1])],
        [int(ref_frame.sum[1][2]), int(ref_frame.sum[1][3])],
    ]

    return {
        "pixel_results": pixelResults,
        "ref_frame": ref_frame,
        "fp_noise": fp_noise,
        "ref_t0": ref_t0,
        "ref_t1": ref_t1,
        "timestamp": time.time(),
    }


def _run_pyplot_frontend(app):
    import matplotlib.pyplot as plt

    columns = Tmf8829Application.pixelColumns(_fpMode)
    rows = Tmf8829Application.pixelRows(_fpMode)
    imFpPixel, imRefPixelT0, imRefPixelT1 = Tmf8829PlotPixelMap.createEmptyPixelMapPlot(columns, rows)

    app.startMeasure()
    dropped_sets = 0
    while plt.fignum_exists(1):
        data = _read_pixel_map_data(app)
        if data is None:
            dropped_sets += 1
            continue
        Tmf8829PlotPixelMap.updatePixelMapPlot(
            imFpPixel, imRefPixelT0, imRefPixelT1, data["pixel_results"], data["ref_frame"]
        )
        plt.pause(0.01)

    if dropped_sets:
        print(f"Skipped {dropped_sets} incomplete measurement set(s).")


def _run_flask_frontend(app, host, port):
    try:
        from flask import Flask, jsonify, Response
    except ModuleNotFoundError as err:
        raise ModuleNotFoundError("Flask is required for --frontend flask. Install it with: pip install flask") from err

    state = {"frame": None, "dropped": 0, "error": None, "running": True}
    state_lock = threading.Lock()

    def _measurement_worker():
        app.startMeasure()
        while True:
            with state_lock:
                if not state["running"]:
                    break
            try:
                data = _read_pixel_map_data(app)
                with state_lock:
                    if data is None:
                        state["dropped"] += 1
                    else:
                        state["frame"] = {
                            "fp_noise": data["fp_noise"],
                            "ref_t0": data["ref_t0"],
                            "ref_t1": data["ref_t1"],
                            "timestamp": data["timestamp"],
                        }
            except Exception as err:
                with state_lock:
                    state["error"] = str(err)
                    state["running"] = False
                break

    worker = threading.Thread(target=_measurement_worker, name="tmf8829-flask-measurement", daemon=True)
    worker.start()

    web = Flask(__name__)

    @web.get("/api/frame")
    def get_frame():
        with state_lock:
            if state["frame"] is None and state["error"] is None:
                return Response(status=204)
            return jsonify({
                "frame": state["frame"],
                "dropped": state["dropped"],
                "error": state["error"],
            })

    @web.get("/")
    def index():
        return """<!doctype html>
<html><head><meta charset="utf-8"><title>TMF8829 Pixel Map</title>
<style>body{font-family:sans-serif;margin:16px}canvas{border:1px solid #444;margin-right:16px}#row{display:flex;gap:16px;flex-wrap:wrap}</style>
</head><body>
<h2>TMF8829 Pixel Map (Flask)</h2>
<div id="meta">Waiting for frames...</div>
<div id="row">
  <div><h3>Focal Plane Noise</h3><canvas id="fp"></canvas></div>
  <div><h3>Reference T0</h3><canvas id="t0"></canvas></div>
  <div><h3>Reference T1</h3><canvas id="t1"></canvas></div>
</div>
<script>
function drawMatrix(canvasId, matrix, cell) {
  if (!matrix || !matrix.length) return;
  const c = document.getElementById(canvasId), ctx = c.getContext('2d');
  const rows = matrix.length, cols = matrix[0].length;
  c.width = cols * cell; c.height = rows * cell;
  let min = Infinity, max = -Infinity;
  for (const r of matrix) for (const v of r) { if (v < min) min = v; if (v > max) max = v; }
  const span = Math.max(1, max - min);
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const t = (matrix[y][x] - min) / span;
      const r = Math.floor(255 * t), b = Math.floor(255 * (1 - t));
      ctx.fillStyle = `rgb(${r},0,${b})`;
      ctx.fillRect(x * cell, y * cell, cell, cell);
    }
  }
}
async function poll() {
  try {
    const res = await fetch('/api/frame');
    if (res.status === 204) return;
    const payload = await res.json();
    if (payload.error) document.getElementById('meta').textContent = 'Error: ' + payload.error;
    if (payload.frame) {
      drawMatrix('fp', payload.frame.fp_noise, 10);
      drawMatrix('t0', payload.frame.ref_t0, 40);
      drawMatrix('t1', payload.frame.ref_t1, 40);
      const ts = new Date(payload.frame.timestamp * 1000).toLocaleTimeString();
      document.getElementById('meta').textContent = `Last frame: ${ts}, dropped sets: ${payload.dropped}`;
    }
  } catch (e) {
    document.getElementById('meta').textContent = 'Fetch error: ' + e;
  }
}
setInterval(poll, 200);
poll();
</script></body></html>"""

    try:
        print(f"Flask frontend at http://{host}:{port}")
        web.run(host=host, port=port, debug=False, use_reloader=False)
    finally:
        with state_lock:
            state["running"] = False
        worker.join(timeout=2.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TMF8829 pixel map visualisation")
    parser.add_argument("--frontend", choices=["pyplot", "flask"], default=_frontend)
    parser.add_argument("--host", default=_flask_host, help="Flask host (only used for --frontend flask)")
    parser.add_argument("--port", type=int, default=_flask_port, help="Flask port (only used for --frontend flask)")
    args = parser.parse_args()

    app = createTmf8829()
    assert app.open()
    try:
        if not app.enable(send_wake_up_sequence=True):
            print("The application did not start up as expected")
            quit(-1)

        app.forceBootmonitor()
        app.blCmdSpiOff()
        app.downloadAndStartApp(hex_file=HEX_FILE)

        appId = app.hal.txRx([0], 4)
        print("[app_id, major, minor, patch] are: ", [f"0x{i:02x}" for i in appId])

        app.configure(period=_use_period, fp_mode=_fpMode, nr_peaks=0, noise_strength=1,
                      full_noise=1, publish=1, iterations=_use_iterations)

        if args.frontend == "flask":
            _run_flask_frontend(app, host=args.host, port=args.port)
        else:
            _run_pyplot_frontend(app)
    finally:
        app.stopMeasure()
        app.disable()
        app.close()
        print("End")
        time.sleep(0.5)
