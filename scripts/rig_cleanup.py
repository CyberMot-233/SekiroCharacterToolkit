"""Dependency-aware cleanup of toolkit-generated affine rigs (Blender 4.5).

Only generated B_<id>/AFF_<id> pairs are deletion candidates. Having animation
curves alone is not a use: the old exporter baked every FLVER node.
"""
import hashlib
import json
import re
from collections import defaultdict

import bpy
import numpy as np

BONE_PATH = re.compile(r'(?:pose\.)?bones\["((?:\\.|[^"\\])*)"\]')
GENERATED = re.compile(r'^(?:AFF|B)_[0-9]+$')


def path_bones(path):
    return [json.loads('"' + m + '"') for m in BONE_PATH.findall(path)]


def curves(action):
    # Iterate channel bags rather than action.fcurves (which only exposes slot 0).
    if action.is_action_layered:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', []):
                    for fc in bag.fcurves:
                        yield bag.fcurves, fc
    else:
        for fc in action.fcurves:
            yield action.fcurves, fc


def action_digest(action, removed=()):
    """Hash surviving animation data including Bezier handles and interpolation."""
    h = hashlib.sha256()
    removed = set(removed)
    for _, fc in curves(action):
        if removed.intersection(path_bones(fc.data_path)):
            continue
        h.update(repr((fc.data_path, fc.array_index, fc.extrapolation, fc.mute)).encode())
        for prop in ('co', 'handle_left', 'handle_right'):
            v = np.empty(len(fc.keyframe_points) * 2, np.float32)
            fc.keyframe_points.foreach_get(prop, v)
            h.update(v.tobytes())
        # RNA foreach_get handles enum identifiers as integers. Avoid Python
        # wrappers for hundreds of millions of keyframes in a full character.
        for prop in ('interpolation', 'handle_left_type', 'handle_right_type'):
            values = np.empty(len(fc.keyframe_points), np.int32)
            fc.keyframe_points.foreach_get(prop, values)
            h.update(values.tobytes())
    return h.hexdigest()


def plan(arm, models):
    names = set(arm.data.bones.keys())
    reasons = defaultdict(set)
    edges = defaultdict(set)
    meshes = []

    def keep(name, reason):
        if name in names:
            reasons[name].add(reason)

    for bone in arm.data.bones:
        if bone.parent:
            edges[bone.name].add(bone.parent.name)
        if not GENERATED.fullmatch(bone.name):
            keep(bone.name, 'non-generated/custom/equipment bone')
        elif bone.name.startswith('B_') and not bone.get('source_name'):
            keep(bone.name, 'unknown provenance')
        if bone.get('sct_keep'):
            keep(bone.name, 'explicit sct_keep')
        for prop in ('bbone_custom_handle_start', 'bbone_custom_handle_end'):
            target = getattr(bone, prop, None)
            if target:
                edges[bone.name].add(target.name)

    source_map = {b.get('source_name'): b.name for b in arm.data.bones if b.get('source_name')}
    for model in models:
        for dummy in model.get('dummies', []):
            for key in ('parent', 'attach'):
                i = dummy.get(key, -1)
                if 0 <= i < len(model['nodes']):
                    keep(source_map.get(model['nodes'][i]['name']), 'source dummy ' + key)

    for ob in bpy.data.objects:
        mods = [m for m in ob.modifiers if m.type == 'ARMATURE' and m.object == arm]
        if mods and ob.type == 'MESH':
            meshes.append(ob)
            weighted = {g.group for v in ob.data.vertices for g in v.groups if g.weight > 0}
            for group in ob.vertex_groups:
                if group.index in weighted:
                    keep(group.name, 'positive vertex weight:' + ob.name)
            if any(m.use_bone_envelopes for m in mods):
                for bone in arm.data.bones:
                    if bone.use_deform:
                        keep(bone.name, 'bone envelope modifier')
            # Other modifiers may consume an otherwise empty group's name.
            for mod in ob.modifiers:
                for prop in mod.bl_rna.properties:
                    if prop.type == 'STRING':
                        value = getattr(mod, prop.identifier, '')
                        keep(value, 'modifier reference:' + ob.name)
        if ob.parent == arm and ob.parent_type == 'BONE':
            keep(ob.parent_bone, 'object bone parent:' + ob.name)
        owners = [(None, ob.constraints)]
        if ob.type == 'ARMATURE':
            owners += [(pb, pb.constraints) for pb in ob.pose.bones]
        for owner, constraints in owners:
            for constraint in constraints:
                if ob == arm and owner:
                    keep(owner.name, 'constraint owner')
                # target/subtarget, pole_target/pole_subtarget, ARMATURE targets
                for prefix in ('', 'pole_'):
                    if getattr(constraint, prefix + 'target', None) == arm:
                        keep(getattr(constraint, prefix + 'subtarget', ''), 'constraint target')
                for target in getattr(constraint, 'targets', []):
                    if target.target == arm:
                        keep(target.subtarget, 'armature constraint target')

    # Include drivers on objects, data, shape keys, node trees, scenes, etc.
    seen = set()
    for prop in bpy.data.bl_rna.properties:
        if prop.type != 'COLLECTION':
            continue
        for block in getattr(bpy.data, prop.identifier, []):
            for item in (block, getattr(block, 'node_tree', None)):
                if item is None or not hasattr(item, 'as_pointer') or item.as_pointer() in seen:
                    continue
                seen.add(item.as_pointer())
                ad = getattr(item, 'animation_data', None)
                if not ad:
                    continue
                for fc in ad.drivers:
                    if item in (arm, arm.data):
                        for name in path_bones(fc.data_path):
                            keep(name, 'driver owner')
                    for variable in fc.driver.variables:
                        for target in variable.targets:
                            if target.id in (arm, arm.data):
                                keep(target.bone_target, 'driver bone target')
                                for name in path_bones(target.data_path):
                                    keep(name, 'driver property target')
                    # Script expressions can access arbitrary bones dynamically.
                    if fc.driver.type == 'SCRIPTED' and ('pose' in fc.driver.expression or 'bpy' in fc.driver.expression):
                        for name in names:
                            keep(name, 'opaque scripted driver (conservative)')

    retained = set(reasons)
    pending = list(retained)
    while pending:
        name = pending.pop()
        for dep in edges[name]:
            if dep not in retained:
                reasons[dep].add('dependency of ' + name)
                retained.add(dep)
                pending.append(dep)
    # Unpaired helper nodes with no dependent B bone can be removed too.
    removed = names - retained
    return {'before': len(names), 'after': len(retained), 'removed_count': len(removed),
            'removed': [{'bone': n, 'source_name': arm.data.bones[n].get('source_name')} for n in sorted(removed)],
            'retained_reasons': {n: sorted(v) for n, v in sorted(reasons.items())}}, meshes


def snapshot(arm, actions, names):
    sc = bpy.context.scene
    saved_action = arm.animation_data.action if arm.animation_data else None
    saved_slot = arm.animation_data.action_slot if arm.animation_data else None
    saved_frame = sc.frame_current + sc.frame_subframe
    result = []
    arm.animation_data_create()
    for ai, action in enumerate(actions or [None]):
        if ai % 25 == 0:
            print('BONE_POSE_CHECK', ai, '/', len(actions), flush=True)
        arm.animation_data.action = action
        if action and action.slots:
            arm.animation_data.action_slot = action.slots[0]
        lo, hi = action.frame_range if action else (saved_frame, saved_frame)
        for f in sorted({float(lo), float((lo + hi) / 2), float(hi)}):
            sc.frame_set(int(f // 1), subframe=f % 1)
            bpy.context.view_layer.update()
            result.append(np.asarray([np.array(arm.matrix_world)] + [np.array(arm.pose.bones[n].matrix) for n in names], dtype=np.float32))
    arm.animation_data.action = saved_action
    if saved_action and saved_slot:
        arm.animation_data.action_slot = saved_slot
    sc.frame_set(int(saved_frame // 1), subframe=saved_frame % 1)
    return np.asarray(result)


def apply_cleanup(arm, report, meshes, actions):
    removed = {r['bone'] for r in report['removed']}
    curve_count = 0
    for action in actions:
        for collection, fc in list(curves(action)):
            if removed.intersection(path_bones(fc.data_path)):
                collection.remove(fc)
                curve_count += 1
    group_count = 0
    for ob in meshes:
        for group in list(ob.vertex_groups):
            if group.name in removed:
                ob.vertex_groups.remove(group)
                group_count += 1
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for name in removed:
        arm.data.edit_bones.remove(arm.data.edit_bones[name])
    bpy.ops.object.mode_set(mode='OBJECT')
    helpers = arm.data.collections.get('SCT · Affine helpers') or arm.data.collections.new('SCT · Affine helpers')
    deform = arm.data.collections.get('SCT · Deform and sockets') or arm.data.collections.new('SCT · Deform and sockets')
    helpers.is_visible = False
    for bone in arm.data.bones:
        if bone.name.startswith('AFF_') or bone.name.endswith('__AFFINE'):
            helpers.assign(bone)
            bone.hide = True
        else:
            deform.assign(bone)
    arm['sct_bone_cleanup_version'] = '0.9.2'
    report.update(removed_fcurves=curve_count, removed_vertex_groups=group_count, helper_collection_hidden=True)
