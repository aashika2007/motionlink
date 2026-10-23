"""SYNTHETIC test geometry written in the TUMFTM file format.

These are analytic shapes for exact-answer tests. They are not circuit data and are
only written to temporary directories during tests.
"""
import math
from pathlib import Path

import numpy as np

STRAIGHT, RADIUS, HALF_WIDTH = 300.0, 60.0, 6.0
STADIUM_LENGTH = 2 * STRAIGHT + 2 * math.pi * RADIUS


def stadium(step=5.0):
    """Counter-clockwise stadium: two 300 m straights, two R = 60 m semicircles."""
    pts = []
    n_s = int(STRAIGHT / step)
    n_a = int(round(math.pi * RADIUS / step))
    for i in range(n_s):
        pts.append((i * step, 0.0))
    for i in range(n_a):
        a = -math.pi / 2 + math.pi * i / n_a
        pts.append((STRAIGHT + RADIUS * math.cos(a), RADIUS + RADIUS * math.sin(a)))
    for i in range(n_s):
        pts.append((STRAIGHT - i * step, 2 * RADIUS))
    for i in range(n_a):
        a = math.pi / 2 + math.pi * i / n_a
        pts.append((RADIUS * math.cos(a), RADIUS + RADIUS * math.sin(a)))
    return np.array(pts)


def figure_eight(n=600, a=200.0):
    """Lemniscate of Gerono: crosses itself at the origin."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([a * np.sin(t), a * np.sin(t) * np.cos(t)])


def stadium_raceline_offsets(centre):
    from motionink.circuits.geometry import cumulative_distance
    s = cumulative_distance(centre, closed=True)
    corner1 = STRAIGHT + math.pi * RADIUS / 2
    corner2 = 2 * STRAIGHT + 1.5 * math.pi * RADIUS
    return -4.0 + 8.0 * (np.exp(-((s - corner1) / 60) ** 2) + np.exp(-((s - corner2) / 60) ** 2))


def write_tumftm(directory, name, centre, w_right, w_left, raceline=None, header="# x_m,y_m,w_tr_right_m,w_tr_left_m"):
    d = Path(directory)
    (d / "tracks").mkdir(parents=True, exist_ok=True)
    rows = [header] if header else []
    wr = np.broadcast_to(w_right, len(centre))
    wl = np.broadcast_to(w_left, len(centre))
    rows += [f"{x:.4f},{y:.4f},{r:.4f},{l:.4f}" for (x, y), r, l in zip(centre, wr, wl)]
    (d / "tracks" / f"{name}.csv").write_text("\n".join(rows) + "\n")
    if raceline is not None:
        (d / "racelines").mkdir(parents=True, exist_ok=True)
        (d / "racelines" / f"{name}.csv").write_text(
            "# x_m,y_m\n" + "\n".join(f"{x:.4f},{y:.4f}" for x, y in raceline) + "\n")


def build_fixture_dir(directory):
    """Writes TestStadium (with race line) and TestEight (no race line)."""
    from motionink.circuits.geometry import left_normals
    c = stadium()
    rl = c + left_normals(c, closed=True) * stadium_raceline_offsets(c)[:, None]
    write_tumftm(directory, "TestStadium", c, HALF_WIDTH, HALF_WIDTH, rl)
    write_tumftm(directory, "TestEight", figure_eight(), 5.0, 5.0)
    return Path(directory)
