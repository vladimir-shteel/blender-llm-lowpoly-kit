"""Silhouette mask metrics on arrays (numpy): the overlap of a build's outline with a target's, the pixels
each has alone, the mean distances between their contours and the connected regions of difference. The
numbers measure two masks in one view; they certify neither internal form nor likeness."""
import math

import numpy as np

from lpk.stages import imaging


def _boundary(mask, unread):
    # A pixel centre is a contour sample if a known neighbour is background.
    # Off-frame/ignored neighbours provide no evidence and never create artificial cut edges.
    out = np.zeros_like(mask)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        a = (slice(max(0, dr), mask.shape[0] + min(0, dr)), slice(max(0, dc), mask.shape[1] + min(0, dc)))
        b = (slice(max(0, -dr), mask.shape[0] - max(0, dr)), slice(max(0, -dc), mask.shape[1] - max(0, dc)))
        out[a] |= mask[a] & ~mask[b] & ~unread[a] & ~unread[b]
    return out


def _distance_line(values):
    # Lower envelope of squared parabolas, exact separable Euclidean distance transform.
    sites = np.flatnonzero(np.isfinite(values))
    if not len(sites):
        return np.full(len(values), np.inf)
    v = np.empty(len(sites), int)
    z = np.empty(len(sites) + 1)
    k, v[0], z[0], z[1] = 0, sites[0], -np.inf, np.inf
    for q in sites[1:]:
        s = ((values[q] + q*q) - (values[v[k]] + v[k]*v[k])) / (2*(q-v[k]))
        while s <= z[k]:
            k -= 1
            s = ((values[q] + q*q) - (values[v[k]] + v[k]*v[k])) / (2*(q-v[k]))
        k += 1
        v[k], z[k], z[k+1] = q, s, np.inf
    x = np.arange(len(values))
    ids = np.searchsorted(z[1:k+1], x, side='left')
    return (x-v[ids])**2 + values[v[ids]]


def distance(mask):
    """(H, W) floats: the exact Euclidean distance in pixels from each pixel centre to the nearest True
    pixel of `mask` ((H, W) bools), 0 on its own pixels, inf everywhere for a mask without one."""
    f = np.where(np.asarray(mask, bool), 0.0, np.inf)
    f = np.asarray([_distance_line(row) for row in f])
    return np.sqrt(np.asarray([_distance_line(col) for col in f.T]).T)


def metrics(build_mask, target_mask, unread=None, names=()):
    """How a build's outline and a target's cover one view's pixels.

    build_mask: (H, W) bools, or ints: the part index (into names) of the build over each pixel, -1 where
    none is. target_mask: (H, W) bools, the target figure. unread: None, or (H, W) bools, pixels read on
    neither side (ignore regions, guessed spans). names: part names by index, which name the parts over
    each region the build alone covers.

    Contours are the pixel centres of a mask with a four-neighbour that is read and background; unread
    neighbours and the image border make no contour. The contour distances are left out (None) when any
    pixel is unread, since a nearest point could otherwise be matched through a boundary nobody saw, and
    when either contour is empty.

    Returns {'iou': overlap over union (None for an empty union), 'build_px', 'target_px', 'overlap_px',
    'extra_px': pixels the build alone covers, 'missing_px': pixels the target alone covers, 'unread_px',
    'touches_border': whether either mask reaches the image border (a figure cut by the frame),
    'build_to_target_px', 'target_to_build_px': the mean distance from each contour sample of one mask to
    the nearest of the other's, 'symmetric_px': their mean, 'diagonal_px': the image diagonal,
    'regions': [{'kind': 'extra' or 'missing', 'area_px', 'box': [x0, y0, x1, y1] (x1 and y1 exclusive),
    'parts': the parts over an extra region}], each 8-connected region of difference, the largest first}.
    Raises ValueError for masks of different shapes."""
    build = np.asarray(build_mask)
    if build.dtype == bool:
        build = np.where(build, 0, -1)
    target = np.asarray(target_mask, bool)
    if build.shape != target.shape:
        raise ValueError('build %r and target %r masks differ in shape' % (build.shape, target.shape))
    unread = np.zeros(target.shape, bool) if unread is None else np.asarray(unread, bool)
    B, F = (build >= 0) & ~unread, target & ~unread
    intersection, union = int((B & F).sum()), int((B | F).sum())
    out = {'iou': intersection / union if union else None, 'build_px': int(B.sum()), 'target_px': int(F.sum()),
           'overlap_px': intersection, 'extra_px': int((B & ~F).sum()), 'missing_px': int((F & ~B).sum()),
           'unread_px': int(unread.sum()),
           'touches_border': any(bool(x[0].any() or x[-1].any() or x[:, 0].any() or x[:, -1].any()) for x in (B, F)),
           'build_to_target_px': None, 'target_to_build_px': None, 'symmetric_px': None,
           'diagonal_px': math.hypot(*target.shape)}
    eb, ef = _boundary(B, unread), _boundary(F, unread)
    if eb.any() and ef.any() and not unread.any():
        d1, d2 = float(distance(ef)[eb].mean()), float(distance(eb)[ef].mean())
        out.update(build_to_target_px=d1, target_to_build_px=d2, symmetric_px=(d1 + d2) / 2)
    regions = []
    for kind, mask in (('extra', B & ~F), ('missing', F & ~B)):
        labels, _ = imaging.components(mask)
        for label in np.unique(labels[mask]):
            pix = labels == label
            rr, cc = np.nonzero(pix)
            parts = [names[i] for i in np.unique(build[pix]) if 0 <= i < len(names)] if kind == 'extra' else []
            regions.append({'kind': kind, 'area_px': len(rr),
                            'box': [int(cc.min()), int(rr.min()), int(cc.max()) + 1, int(rr.max()) + 1],
                            'parts': parts})
    regions.sort(key=lambda r: (-r['area_px'], r['kind'], r['box']))
    out['regions'] = regions
    return out
