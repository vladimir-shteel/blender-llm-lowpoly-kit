"""Host cases of the mask metrics (lpk.stages.numerical.metrics): overlap, contour distances against brute
force, unread pixels, empty and disjoint masks, region owners; the review rasterizer's depth ties; and the
raw rest guard of the review's geometry reader."""
import math
import time
import types

import numpy as np

from test_review_instruments import review

n = review.numerical
FIT = dict(yaw=0, pitch=0, s=1, ox=0, oy=0)


def test_disconnected_target_and_local_missing_region():
    mask = np.zeros((24, 24), bool); mask[3:12, 3:12] = True; mask[18:20, 18:20] = True
    candidate = mask.copy(); candidate[18:20, 18:20] = False
    r = n.metrics(candidate, mask, names=['body'])
    assert r['iou'] == 81 / 85 and r['missing_px'] == 4 and r['extra_px'] == 0
    assert r['overlap_px'] == 81 and r['target_px'] == 85 and r['build_px'] == 81
    assert r['regions'] == [{'kind': 'missing', 'area_px': 4, 'box': [18, 18, 20, 20], 'parts': []}]
    assert n.metrics(mask, mask)['iou'] == 1


def test_contours_known_translation_and_exact_distance_transform():
    mask = np.zeros((25, 30), bool); mask[5:17, 6:15] = True
    shifted = np.roll(mask, 2, axis=1)
    r = n.metrics(shifted, mask)
    a = n._boundary(shifted, np.zeros_like(mask)); b = n._boundary(mask, np.zeros_like(mask))
    aa, bb = np.argwhere(a), np.argwhere(b)
    pair = np.sqrt(((aa[:, None, :] - bb[None, :, :]) ** 2).sum(axis=2))
    assert math.isclose(r['build_to_target_px'], pair.min(axis=1).mean())
    assert math.isclose(r['target_to_build_px'], pair.min(axis=0).mean())
    assert math.isclose(r['symmetric_px'], (pair.min(axis=1).mean() + pair.min(axis=0).mean()) / 2)
    assert math.isclose(r['diagonal_px'], math.hypot(*mask.shape))
    rng = np.random.default_rng(3)
    points = rng.random((13, 15)) < 0.08
    coords = np.indices(points.shape).transpose(1, 2, 0)
    expected = np.sqrt(((coords[:, :, None, :] - np.argwhere(points)[None, None, :, :]) ** 2).sum(axis=3).min(axis=2))
    assert np.allclose(n.distance(points), expected)


def test_unread_pixels_and_no_artificial_cut_contours():
    mask = np.zeros((24, 24), bool); mask[4:20, 4:20] = True
    ignored = np.zeros_like(mask); ignored[:, 11:13] = True
    uncertain = np.zeros_like(mask); uncertain[4:8, 4:8] = True
    candidate = mask.copy(); candidate[ignored | uncertain] = False
    r = n.metrics(candidate, mask, unread=ignored | uncertain)
    assert r['iou'] == 1 and r['symmetric_px'] is None and r['unread_px'] == 48 + 16
    edge = n._boundary(mask & ~ignored, ignored)
    assert not edge[8:16, 10].any() and not edge[8:16, 13].any()


def test_empty_disjoint_and_border_touching_masks():
    mask = np.zeros((24, 24), bool); mask[4:8, 4:8] = True
    empty = np.zeros_like(mask)
    assert n.metrics(empty, empty)['iou'] is None
    r = n.metrics(empty, mask)
    assert r['iou'] == 0 and r['build_px'] == 0 and r['symmetric_px'] is None
    away = np.zeros_like(mask); away[14:18, 14:18] = True
    r = n.metrics(away, mask)
    assert r['overlap_px'] == 0 and r['iou'] == 0 and r['symmetric_px'] > 0
    assert not r['touches_border']
    edge = mask.copy(); edge[0, 4] = True
    assert n.metrics(edge, mask)['touches_border']
    try:
        n.metrics(mask, mask[:10])
    except ValueError as e:
        assert 'shape' in str(e)
    else:
        raise AssertionError('masks of two shapes compared')


def test_crossing_triangle_depth_stable_ties_and_triangle_source_ids():
    co=np.array([[1,0,-1],[9,8,-1],[1,0,-9],[1,3,-1],[9,3,-1],[1,3,-9]],float)
    tri=np.array([[0,1,2],[3,4,5]])
    ids,source=review._paint(co,tri,[0,1],FIT,(12,12),triangle_ids=True)
    assert ids[3,3]==0 and source[3,3]==0
    assert ids[2,6]==1 and source[2,6]==1
    tied=co.copy();tied[:,1]=0
    ids,source=review._paint(tied,tri,[4,7],FIT,(12,12),triangle_ids=True)
    assert ids[3,3]==4 and source[3,3]==0
    reversed_ids=review._paint(co,tri[::-1],[1,0],FIT,(12,12))
    assert np.array_equal(ids>=0,reversed_ids>=0)
    assert reversed_ids[3,3]==0 and reversed_ids[2,6]==1
    uv=np.column_stack((co[:,0],-co[:,2]))
    assert np.array_equal(review.checks.cover(uv[tri],(12,12)),source>=0)


def test_extra_regions_name_the_parts_over_them():
    mask = np.zeros((16, 16), bool); mask[5:10, 5:10] = True
    build = np.where(mask, 0, -1); build[5:10, 10:12] = 1
    r = n.metrics(build, mask, names=['body', 'shell'])
    extra, = r['regions']
    assert extra == {'kind': 'extra', 'area_px': 10, 'box': [10, 5, 12, 10], 'parts': ['shell']}


def test_raw_rest_guard_refuses_visible_deformation_without_resetting_it():
    class Mesh(dict):
        pass
    co=np.array([[3,0,-3],[8,0,-3],[3,0,-8]],float)
    tri=np.array([[0,1,2]])
    mesh=Mesh(parts=['head']);mesh.name='Mesh';mesh.type='MESH'
    mesh.data=types.SimpleNamespace(attributes={'part':object()},shape_keys=None)
    mesh.modifiers=[]
    pose_matrix=np.eye(4)
    bone=types.SimpleNamespace(name='Head',matrix=pose_matrix,
                               bone=types.SimpleNamespace(matrix_local=np.eye(4),bbone_segments=1))
    arm=types.SimpleNamespace(name='Rig',data=types.SimpleNamespace(pose_position='POSE'),
                              pose=types.SimpleNamespace(bones=[bone]))
    modifier=types.SimpleNamespace(name='RigDeform',type='ARMATURE',object=arm,show_viewport=True)
    saved_data=getattr(review.bpy,'data',None);saved_read=review.checks.read_mesh
    reads=[]
    try:
        review.bpy.data=types.SimpleNamespace(objects={'Mesh':mesh})
        def read(name):
            reads.append(name)
            return None,co.copy(),np.zeros(3,int),tri.copy(),['head']
        review.checks.read_mesh=read
        mesh.modifiers=[modifier]
        assert np.array_equal(review._geometry(['Mesh'])[0],co), 'ordinary identity armature is raw-rest compatible'
        before=len(reads)
        pose_matrix[0,3]=0.25
        views=types.SimpleNamespace(names=['front'],image=lambda view:'not-read.png')
        try:review.outline_diff(views,'front',FIT,['Mesh'])
        except ValueError as error:
            assert 'non-rest' in str(error) and 'raw rest mesh' in str(error)
        else:raise AssertionError('posed geometry produced a purported rest-mask comparison')
        assert len(reads)==before and pose_matrix[0,3]==0.25, 'guard must neither read raw geometry nor reset pose'
        arm.data.pose_position='REST'
        assert np.array_equal(review._geometry(['Mesh'])[0],co), 'explicit rest display is supported'
        assert pose_matrix[0,3]==0.25, 'rest-display guard preserves retained pose channels'
        mesh.modifiers=[]
        mesh.data.shape_keys=types.SimpleNamespace(use_relative=True,key_blocks=[
            types.SimpleNamespace(value=0,mute=False),types.SimpleNamespace(value=1,mute=False)])
        try:review._geometry(['Mesh'])
        except ValueError as error:assert 'shape key' in str(error)
        else:raise AssertionError('active shape key was ignored')
        mesh.data.shape_keys.key_blocks[1].value=0
        assert np.array_equal(review._geometry(['Mesh'])[0],co), 'inactive relative keys preserve raw basis'
        mesh.modifiers=[types.SimpleNamespace(name='Subdivision',type='SUBSURF',show_viewport=True)]
        try:review._geometry(['Mesh'])
        except ValueError as error:assert 'viewport modifier' in str(error)
        else:raise AssertionError('shape-changing modifier was ignored')
        mesh.modifiers[0].show_viewport=False
        assert np.array_equal(review._geometry(['Mesh'])[0],co), 'disabled modifier does not deform visible geometry'
    finally:
        review.checks.read_mesh=saved_read
        if saved_data is None:delattr(review.bpy,'data')
        else:review.bpy.data=saved_data


if __name__=='__main__':
    t=time.perf_counter()
    for name,fn in sorted(globals().copy().items()):
        if name.startswith('test_') and callable(fn):
            fn();print('ok',name)
    print('seconds',round(time.perf_counter()-t,3))
