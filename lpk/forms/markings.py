"""Body markings as colour sources: patterns wrapped round a body segment and baked into the atlas."""
import math
from mathutils import Vector

from lpk.core.shapes import axis_fill, mark


def wrapped_stripes(b, part, bvh, a, c, ref, rows, col, start=9.0, alt=3.0, steps=6, wave=0.008, freq=9.0, lift=0.002):
    """Tiger stripes across a segment's axis a -> c (a head along its length): each row a band from
    near the top midline (`start` degrees off `ref`, every other row `alt` further) down one side and
    mirrored on the other, wavy, leaning back toward a as it runs down and tapering only near its end,
    so the midline stays clear. rows: (s from a in metres, reach in degrees from
    `ref`, width, lean in metres over the length). A stripe's width times its part's texels per metre
    must reach lpk.stages.texture.MIN_LINE_TEXELS, or it bakes as dashes: a texel boost on its part
    raises the density, and the texel readings use the width recorded at every point (shapes.mark), the
    taper included. The taper stays near the end, since one over the whole length would leave much of each
    stripe under a texel.
    Units: wave m, freq rad over a stripe, lift m."""
    av, ax = Vector(a), (Vector(c) - Vector(a)).normalized()
    r0 = Vector(ref); r0 = (r0 - ax * r0.dot(ax)).normalized(); r1 = ax.cross(r0)
    for k, (s0, reach, w0, lean) in enumerate(rows):
        for sgn in (1, -1):
            a0 = start + alt * (k % 2)
            pts_a, pts_b, centres, widths = [], [], [], []
            for i in range(steps + 1):
                t = i / steps
                az = a0 + (reach - a0) * t
                wv = wave * math.sin(t * freq + k * 1.7)
                half = w0 * (1 - t ** 2.5) * 0.5 + 0.001
                s = s0 - lean * t + wv
                pts_a.append((sgn * az, s - half)); pts_b.append((sgn * az, s + half))
                # The stripe's centre cast as axis_fill casts its points, for the texel record only.
                dr = r0 * math.cos(math.radians(sgn * az)) + r1 * math.sin(math.radians(sgn * az))
                hit = bvh.ray_cast(av + ax * s + dr * 0.5, -dr, 0.5)[0]
                if hit is not None:
                    centres.append(hit)
                    widths.append(2 * half)
            axis_fill(b, part, bvh, a, c, ref, pts_a + list(reversed(pts_b)), col, lift=lift, level=1)
            if centres:
                mark(b, 'wrapped_stripes', part, w0, centres, widths=widths)
