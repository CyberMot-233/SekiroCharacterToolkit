"""Author the final rig/actions directly, without intermediate Blender projects.

The former flat affine playback is evaluated numerically one clip at a time.
It never becomes a second set of Blender Actions or an on-disk pose cache.
"""
import json
import math
from collections import OrderedDict
import bpy
import numpy as np
from mathutils import Matrix, Vector
from affine_factor import factor_affine
from hierarchy_math import local_basis, trs_residual
from internal_fk_verified import DEFAULT_C, _quaternion_matrices, fk_separate_scale
from flver_mapping import mapped_fk
from restore_hierarchy import decomp, write, set_action, frame
from rig_cleanup import plan, apply_cleanup


def converted(v):
    return DEFAULT_C @ np.asarray(v).reshape(4, 4).T @ np.linalg.inv(DEFAULT_C)


def compose(rows):
    mats = _quaternion_matrices(rows[:, 3:7][:, [1, 2, 3, 0]])
    mats[:, :3, :3] *= rows[:, None, 7:]
    mats[:, :3, 3] = rows[:, :3]
    return mats


def interpolate_trs(rows, source_frames, frames):
    # Match Blender's float32 LINEAR FCurves, with quaternion normalization.
    rows = rows.astype(np.float32)
    result = np.column_stack([np.interp(frames, source_frames.astype(np.float32), rows[:, i]) for i in range(10)])
    return compose(result)


class SourceMotion:
    def __init__(self, folder, pkg, clip, nodes, original_rest, original_names, face, report):
        self.clip = clip
        self.nodes = nodes
        self.rest = original_rest
        self.original_names = original_names
        self.frames = 1 + np.arange(clip['frames']) * clip['dt'] * 30
        sk = pkg['skeleton']; refs = np.asarray([b['trs'] for b in sk], float)
        raw = np.fromfile(folder / clip['file'], dtype='<f4').reshape(clip['frames'], len(clip['map']), 10)
        local = np.broadcast_to(refs, (clip['frames'], len(sk), 10)).copy()
        for ti, bi in enumerate(clip['map']):
            if not 0 <= bi < len(sk): raise ValueError('Animation track outside source skeleton')
            local[:, bi] = raw[:, ti]
        local = face.apply(clip, local, report)
        fk = fk_separate_scale([b['parent'] for b in sk], local[:, :, :3], local[:, :, 3:7], local[:, :, 7:], DEFAULT_C)
        self.fk = mapped_fk(nodes, {b['name']: i for i, b in enumerate(sk)}, fk)
        self.factors = {}

    def skin(self, name, frames):
        bindinv = np.linalg.inv(converted(self.nodes[name]['world']))
        if name not in self.original_names:
            # Unweighted anatomical connectors follow the old verified restoration.
            values = self.fk[name] @ bindinv
            return np.column_stack([np.interp(frames, self.frames, values[:, i, j])
                                    for i in range(4) for j in range(4)]).reshape(-1, 4, 4)
        if name not in self.factors:
            rest = self.rest[name]
            basis = np.linalg.inv(rest) @ self.fk[name] @ bindinv @ rest
            outer, inner = factor_affine(basis)
            self.factors[name] = (decomp(outer)[0], decomp(inner)[0])
        outer, inner = self.factors[name]
        return self.rest[name] @ interpolate_trs(outer, self.frames, frames) @ interpolate_trs(inner, self.frames, frames) @ np.linalg.inv(self.rest[name])


class FinalRig:
    def __init__(self, arm, models, nodes, rig_names, rest, clean, hierarchy):
        self.arm, self.nodes, self.hierarchy = arm, nodes, hierarchy
        self.original_rest = dict(rest)
        self.helpers = set()
        self.actions = []; self.action_count = 0
        self.max_error = 0.0; self.checks = 0; self.native_fallbacks = 0
        self.max_single_trs_residual = 0.0
        self.cleanup = None
        if clean:
            self.cleanup, meshes = plan(arm, models)
            apply_cleanup(arm, self.cleanup, meshes, [])
            self.cleanup.update(passed=True, method='dependency cleanup before any Action exists', pose_rebake_count=0)
        self.source = {n: pair[1] for n, pair in rig_names.items() if pair[1] in arm.data.bones}
        self.original_names = set(self.source)
        self.names = list(self.source)
        self.rig_names = {n: pair for n, pair in rig_names.items() if n in self.source}
        if not hierarchy:
            self.rest = {n: rest[n] for n in self.names}
            return
        closure = set(self.names)
        for n in self.names:
            seen = set(); parent = nodes[n].get('_parent_name')
            while parent:
                if parent in seen: raise ValueError('Source hierarchy cycle')
                seen.add(parent); closure.add(parent); parent = nodes[parent].get('_parent_name')
        def depth(n):
            d = 0
            while nodes[n].get('_parent_name'): d += 1; n = nodes[n]['_parent_name']
            return d
        self.names = sorted(closure, key=lambda n: (depth(n), n))
        old_helpers = [self.rig_names[n][0] for n in self.source]
        for n, old in self.source.items(): arm.data.bones[old].name = 'SCT_TMP_' + old
        for n, old in self.source.items(): arm.data.bones['SCT_TMP_' + old].name = n
        bpy.context.view_layer.objects.active = arm; bpy.ops.object.mode_set(mode='EDIT')
        for n in old_helpers: arm.data.edit_bones.remove(arm.data.edit_bones[n])
        for n in self.names:
            eb = arm.data.edit_bones.get(n) or arm.data.edit_bones.new(n)
            loc, q, _ = Matrix(converted(nodes[n]['world'])).decompose()
            eb.parent = None; eb.head = loc; eb.tail = loc + q @ Vector((0, .05, 0))
            eb.matrix = Matrix.Translation(loc) @ q.to_matrix().to_4x4(); eb.length = .05
            eb.use_deform = n in self.source; eb.inherit_scale = 'NONE'; eb.use_connect = False
        special = {'Master':'Root','Root':'Spine','Pelvis':'Spine','Spine':'Spine1','Spine1':'Spine2','Spine2':'Neck','Neck':'Head'}
        for s in ('L', 'R'):
            special.update({s+'_Clavicle':s+'_UpperArm',s+'_UpperArm':s+'_Forearm',s+'_Forearm':s+'_Hand',s+'_Thigh':s+'_Calf',s+'_Calf':s+'_Foot',s+'_Foot':s+'_Toe0',s+'_Hand':s+'_Finger2'})
        for n in self.names:
            eb = arm.data.edit_bones[n]; candidate = special.get(n)
            children = [c for c in self.names if nodes[c].get('_parent_name') == n and (arm.data.edit_bones[c].head-eb.head).length > .004]
            if candidate not in closure: candidate = None
            if candidate is None and children:
                candidate = min(children, key=lambda c: ('twist' in c.lower() or 'dummy' in c.lower(), (arm.data.edit_bones[c].head-eb.head).length))
            if candidate and (arm.data.edit_bones[candidate].head-eb.head).length > .004: eb.tail = arm.data.edit_bones[candidate].head
            else: eb.length = .022 if depth(n) > 6 else .065
        for n in self.names:
            parent = nodes[n].get('_parent_name')
            arm.data.edit_bones[n].parent = arm.data.edit_bones.get(parent) if parent else None
        bpy.ops.object.mode_set(mode='OBJECT')
        self.rest = {n: np.array(arm.data.bones[n].matrix_local) for n in self.names}
        self.rig_names = {n: (None, n) for n in self.names}
        collection = arm.data.collections.get('SCT · Deform and sockets') or arm.data.collections.new('SCT · Deform and sockets')
        for n in self.names:
            b = arm.data.bones[n]; b['source_name'] = n; b['source_parent_name'] = nodes[n].get('_parent_name') or ''
            b['sct_hierarchy_bone'] = True; b.hide = False; collection.assign(b)
            arm.pose.bones[n].rotation_mode = 'QUATERNION'
        arm['sct_hierarchy_version'] = '0.10.4-direct'; arm.data.display_type = 'OCTAHEDRAL'; arm.show_in_front = True

    def add_helpers(self, names):
        fresh = set(names) - self.helpers
        if not fresh: return
        arm = self.arm
        bpy.context.view_layer.objects.active = arm; bpy.ops.object.mode_set(mode='EDIT')
        for n in sorted(fresh):
            eb = arm.data.edit_bones[n]; helper = arm.data.edit_bones.new('AFF::' + n)
            helper.head = eb.head.copy(); helper.tail = eb.tail.copy(); helper.roll = eb.roll
            helper.parent = eb.parent; helper.use_deform = False; helper.inherit_scale = 'NONE'
            eb.parent = helper; eb.inherit_scale = 'FULL'; eb.use_connect = False
        bpy.ops.object.mode_set(mode='OBJECT')
        collection = arm.data.collections.get('SCT · Affine helpers') or arm.data.collections.new('SCT · Affine helpers')
        identity = np.array([[0,0,0,1,0,0,0,1,1,1]], float)
        for n in fresh:
            helper = arm.data.bones['AFF::' + n]; helper['sct_affine_helper'] = True; collection.assign(helper)
            arm.pose.bones[helper.name].rotation_mode = 'QUATERNION'
            if np.max(abs(np.array(helper.matrix_local) - self.rest[n])) > 2e-6: raise ValueError('Helper rest mismatch: ' + n)
            # Earlier clips were shear-free here. Move their TRS onto the new
            # outer bone and write identity on the inner; no re-sampling/rebake.
            prefix = 'pose.bones[' + json.dumps(n) + '].'
            replacement = 'pose.bones[' + json.dumps(helper.name) + '].'
            for action in self.actions:
                for fc in action.fcurves:
                    if fc.data_path.startswith(prefix): fc.data_path = replacement + fc.data_path[len(prefix):]
                write(action, n, np.array([1.0]), identity)
        self.helpers.update(fresh)

    def bake(self, action, motion):
        frames = motion.frames
        if not self.hierarchy:
            for n in self.names:
                basis = np.linalg.inv(self.rest[n]) @ motion.skin(n, frames) @ self.rest[n]
                outer, inner = factor_affine(basis)
                write(action, self.rig_names[n][0], frames, decomp(outer)[0])
                write(action, self.rig_names[n][1], frames, decomp(inner)[0])
            dense = frames
        else:
            dense = np.unique(np.concatenate([frames] + [frames[:-1] + np.diff(frames)*i/8 for i in range(1,8)]))
            targets = OrderedDict()
            def target(n):
                if n not in targets:
                    targets[n] = motion.skin(n, dense) @ self.rest[n]
                    if len(targets) > 4: targets.popitem(last=False)
                return targets[n]
            for n in self.names:
                par = self.nodes[n].get('_parent_name'); t = target(n); pt = target(par) if par else None
                values = local_basis(t, self.rest[n], pt, self.rest[par] if par else None)
                bone = self.arm.data.bones['AFF::'+n if n in self.helpers else n]
                native_error = 0.0
                for k in sorted({0, len(dense)//2, len(dense)-1}):
                    kw = {'parent_matrix': Matrix(pt[k]), 'parent_matrix_local': Matrix(self.rest[par])} if par else {}
                    native = np.array(bone.convert_local_to_pose(Matrix(t[k]), Matrix(self.rest[n]), invert=True, **kw))
                    native_error = max(native_error, float(np.max(abs(native-values[k]))))
                if native_error > 2e-5:
                    self.native_fallbacks += 1
                    values = np.array([np.array(bone.convert_local_to_pose(Matrix(t[k]), Matrix(self.rest[n]), invert=True, **({'parent_matrix': Matrix(pt[k]), 'parent_matrix_local': Matrix(self.rest[par])} if par else {}))) for k in range(len(dense))])
                residual = trs_residual(values); self.max_single_trs_residual = max(self.max_single_trs_residual, residual)
                if residual > 2e-6: self.add_helpers([n])
                if n in self.helpers:
                    outer, inner = factor_affine(values)
                    write(action, 'AFF::'+n, dense, decomp(outer)[0]); write(action, n, dense, decomp(inner)[0])
                else: write(action, n, dense, decomp(values)[0])
        self.actions.append(action); self.action_count += 1
        return dense

    def verify(self, action, motion, dense):
        set_action(self.arm, action)
        indices = sorted(set(range(0, len(dense), 8 if self.hierarchy else 1)) | set(np.linspace(0,len(dense)-1,9,dtype=int)))
        frames = dense[indices]
        expected = {n: motion.skin(n, frames) for n in self.names}
        inv = {n: np.linalg.inv(self.rest[n]) for n in self.names}
        worst = 0.0
        for k, f in enumerate(frames):
            frame(float(f))
            for n in self.names:
                actual = np.array(self.arm.pose.bones[self.rig_names[n][1]].matrix) @ inv[n]
                err = float(np.max(abs(actual-expected[n][k]))); worst = max(worst,err); self.checks += 1
        self.max_error = max(self.max_error, worst)
        if worst > 5e-4: raise ValueError(f'Direct stored skin mismatch {action.name}: {worst}')
        return worst

    def report(self):
        return dict(passed=self.max_error < 5e-4, version='0.10.4-direct', method='direct final hierarchy; one clip at a time; no intermediate blend or pose cache',
                    source_bones=len(self.names), bones_after=len(self.arm.data.bones), affine_helpers=len(self.helpers),
                    helper_bones=sorted(self.helpers), actions=self.action_count, matrix_checks=self.checks,
                    max_skin_matrix_error=self.max_error, max_single_trs_residual=self.max_single_trs_residual, native_fallbacks=self.native_fallbacks,
                    hierarchy={n:self.nodes[n].get('_parent_name') for n in self.names},
                    scope='all actions/source frames plus 9 dense samples; fractional interpolation approximate')
