"""Validated embedded-weapon appearance policies, independent of Blender.

HKX reference transforms are not a substitute for a missing weapon track.
Emma's masks 0/2 are alternate hand/sheathed swords. A combat clip often
omits Katana completely, while NpcParam 74000000 still enables mask 2.
Only switch these verified variants; never change bind matrices or geometry.
TAE 233/711/713 is applied AFTER this base state, and native scale keys remain.
Unknown characters and explicit fixed appearances are left untouched.
"""
import json
from pathlib import Path

VERSION = '0.10.6'

class NpcWeaponPolicy:
    def __init__(self, pkg, folder):
        self.pkg = pkg
        appearance = pkg.get('npcAppearance', {})
        self.default = list((appearance.get('selected') or {}).get('drawMask', [True] * 32))
        self.mode = appearance.get('weapon_policy',
            'fixed' if appearance.get('selection') == 'explicit NpcParam ID' else 'auto')
        if self.mode not in ('auto', 'fixed'):
            raise ValueError('Unknown NPC weapon policy: ' + str(self.mode))
        self.variants = {}
        self.reason = 'fixed appearance' if self.mode == 'fixed' else 'no verified embedded-weapon profile'
        if self.mode != 'auto' or pkg.get('character') != 'c7400':
            return
        if not any(self.default[i] for i in (0, 2, 4)):
            self.reason = 'selected unarmed NPC appearance retained'
            return
        # Gate the profile against real FLVER mesh weights/material masks, not
        # mesh ordinal or a name guessed from a screenshot.
        import re
        found = {}
        for file in pkg['models']:
            model = json.loads((Path(folder) / file).read_text('utf-8-sig'))
            if model['version'] <= 0x2000D:
                continue
            for mesh in model['meshes']:
                mat = model['materials'][mesh['material']]['name']
                match = re.search(r'#([0-9]+)#', mat)
                if not match or int(match[1]) not in (0, 2) or not mesh['usesBoneIndices']:
                    continue
                names = {model['nodes'][i]['name'] for ids, weights in zip(mesh['boneIndices'], mesh['weights'])
                         for i, w in zip(ids, weights) if w > 0 and 0 <= i < len(model['nodes'])}
                found.setdefault(int(match[1]), set()).update(names)
        expected = {0: {'R_Katana'}, 2: {'Katana'}}
        if found != expected:
            self.reason = 'c7400 weapon schema differs; original masks retained'
            return
        self.variants = {0: 'R_Katana', 2: 'Katana'}
        self.reason = 'c7400 verified FLVER mask/weight pairs + HKX track presence; native scale and TAE retained'

    def resolve(self, clip):
        result = list(self.default)
        tracked = {self.pkg['skeleton'][int(i)]['name'] for i in clip['map'] if 0 <= int(i) < len(self.pkg['skeleton'])}
        changes = []
        if self.variants:
            for mask, name in self.variants.items():
                enabled = name in tracked
                if result[mask] != enabled:
                    changes.append({'mask': mask, 'bone': name, 'before': result[mask], 'after': enabled})
                result[mask] = enabled
        return result, {'version': VERSION, 'mode': self.mode, 'reason': self.reason,
                        'changed_masks': changes, 'tracked_weapon_bones': sorted(tracked & set(self.variants.values()))}
