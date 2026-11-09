"""Wait until an X display has drawn something and stopped changing, then save a PNG.

Usage:
  python3 grab_stable.py DISPLAY OUT.png [--timeout 60] [--settle 4]
                        [--tolerance 0.03] [--crop WxH+X+Y]

Polls the root window every 0.5 s with ImageMagick ``import``. Saves once the
screen is not all one color and the last --settle grabs differ by at most
--tolerance of the screen (a blinking text cursor never stops changing).
Exit 1 on timeout (still saves the last grab so you can see why).
Needs only ImageMagick (``import``, ``convert``); no PIL, no xdotool.
"""

import argparse
import subprocess
import sys
import time


def grab_raw(display):
    out = subprocess.run(["import", "-display", display, "-window", "root", "rgb:-"],
                         capture_output=True, check=True).stdout
    return out


def _changed(a, b, chunk=4096):
    """Fraction of fixed-size byte chunks that differ."""
    n = (len(a) + chunk - 1) // chunk
    return sum(a[i:i + chunk] != b[i:i + chunk] for i in range(0, len(a), chunk)) / max(1, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("display")
    ap.add_argument("out")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--settle", type=int, default=4)
    ap.add_argument("--tolerance", type=float, default=0.03,
                    help="fraction of the screen allowed to keep changing")
    ap.add_argument("--crop", default=None, help="WxH+X+Y region to keep")
    a = ap.parse_args()

    deadline = time.time() + a.timeout
    last, same, ok = None, 0, False
    while time.time() < deadline:
        raw = grab_raw(a.display)
        blank = len(set(raw[i:i + 3] for i in range(0, min(len(raw), 3_000_000), 3 * 97))) <= 1
        settled = last is not None and len(last) == len(raw) and _changed(last, raw) <= a.tolerance
        same = same + 1 if (settled and not blank) else 0
        last = raw
        if same >= a.settle - 1:
            ok = True
            break
        time.sleep(0.5)

    cmd = ["import", "-display", a.display, "-window", "root"]
    if a.crop:
        cmd += ["-crop", a.crop, "+repage"]
    subprocess.run(cmd + [a.out], check=True)
    print(("stable: " if ok else "TIMEOUT (screen still changing or blank): ") + a.out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
