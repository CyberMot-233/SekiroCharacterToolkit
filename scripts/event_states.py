"""Sekiro equipment TAE state, reproduced from DSAnimStudio 5 RC6.1.

No bpy and no third-party dependencies. Data is loaded lazily from this directory.

    s = get_state('namespace/a106_316210', 2.426)
    assert s['dummies']['MB'] == [20, 149, -1, -1]
    s = get_state('a073_400000', 0.3)
    assert s['dummies']['L'] == [-1, 21, -1, -1]

Times are seconds and converted to float32, as in DSAS. prev_t=None means a
stationary sample (closed interval [start,end]). Supplying prev_t reproduces
DSAS's enter/exit frame behavior, including one update after crossing an end.
Do not subtract an event's start time when sampling a weapon's internal HKX.

key_kind='auto' prefers an exact TAE ID, then reverse-maps an HKX ID. For actions
known to be actual HKX clips use key_kind='hkx'. Ambiguous HKX-only matches with
no exact TAE candidate raise AmbiguousAnimationError; get_candidates() exposes
all alternatives, and tae_key= selects one explicitly. Namespaced Blender names,
.hkx/.hkt suffixes, and Blender .001 duplicate suffixes are accepted.

Evidence (all files under ../audit_weapon_repo/verified_src match install PDB):
  TaeEditor/TaeActionSimulationEnvironment.cs:246,266,373-375,393-397,739-769,
    817-819,896-914,1261-1264,1388-1481.
  NewEquipSlot_Weapon.cs:245-280,417-420,567-573.
  ParamData/ParamData.EquipParamWeapon.cs:194-226,268-269.
  ParamData/ParamData.WepAbsorpPosParam.cs:128-180.
  DSAProj/DSAProj.Animation.cs:341-359.

Only the three requested slots R/L/MB are modeled. Grappling-hook events are
reported as ignored. 712 is ignored for SDT. User visibility, GUI mute/solo,
overlay animation slots, debug forced visibility, and cross-clip combo state
are outside this single-clip evaluator. previous_state= may preserve Absorp
when a style 0/4/5 is selected, matching DSAS's lack of an assignment for those
styles. Otherwise Absorp history is reconstructed from the clip's style events
starting at OneHand (or start_weapon_style=).
"""
from __future__ import annotations

import collections
import json
import math
from pathlib import Path
import re
import struct

SLOT_EQUIP_IDS = {"R": 8000000, "L": 73000, "MB": 9700000}
SLOT_MODEL_IDS = {"R": 300, "L": 730, "MB": 310}
MODEL_TYPE_SLOTS = {0: "R", 1: "L", 2: "MB", 3: "GH"}
STYLE_NAMES = {0: "None", 1: "OneHand", 2: "LeftBoth", 3: "RightBoth",
               4: "OneHandTransformedL", 5: "OneHandTransformedR"}
_ANIM_RE = re.compile(r"a(\d+)_(\d{6})(?!\d)", re.I)


def _f32(value):
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def anim_key(full_id):
    full_id = int(full_id)
    if full_id < 0:
        raise ValueError("Negative animation ID")
    return f"a{full_id // 1000000:03d}_{full_id % 1000000:06d}"


def normalize_action_key(value):
    """Return canonical aNNN_NNNNNN, preserving the full namespace number."""
    if isinstance(value, int):
        return anim_key(value)
    matches = list(_ANIM_RE.finditer(str(value)))
    if matches:
        m = matches[-1]
        return f"a{int(m.group(1)):03d}_{int(m.group(2)):06d}"
    if str(value).isdigit():
        return anim_key(int(value))
    raise ValueError(f"No Sekiro animation ID in {value!r}")


def _full_id(key):
    m = _ANIM_RE.fullmatch(key)
    return int(m.group(1)) * 1000000 + int(m.group(2))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


class AmbiguousAnimationError(ValueError):
    def __init__(self, resolution):
        self.resolution = resolution
        super().__init__(f"HKX {resolution['hkx_key']} has different TAE event sources: "
                         + ", ".join(x['tae_key'] for x in resolution['candidates'])
                         + "; select tae_key explicitly")


class EventStateDatabase:
    def __init__(self, data_dir=None, *, model_presence=None, start_weapon_style=1):
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parent
        self.start_weapon_style = int(start_weapon_style)
        self.animations = {}
        self._resolved = {}
        self.hkx_to_tae = collections.defaultdict(list)
        self.reference_errors = []
        self.event_counts = collections.Counter()
        categories = _read_json(self.data_dir / "character_tae.json")
        for category in categories:
            match = re.search(r"a(\d+)\.tae$", category['name'], re.I)
            if not match:
                raise ValueError(f"Unrecognized TAE category {category['name']!r}")
            namespace = int(match.group(1))
            for raw_anim in category['animations']:
                raw_id = int(raw_anim['id'])
                full = namespace * 1000000 + raw_id if raw_id < 1000000 else raw_id
                key = anim_key(full)
                if key in self.animations:
                    raise ValueError(f"Duplicate TAE animation {key}")
                events = []
                for index, ev in enumerate(raw_anim.get('events', [])):
                    ev = dict(ev)
                    ev['index'] = index  # Preserve original TAE order, not start-time order.
                    ev['start'] = _f32(ev['start'])
                    ev['end'] = _f32(ev['end'])
                    ev['_bytes'] = bytes.fromhex(ev.get('raw', ''))
                    events.append(ev)
                    self.event_counts[int(ev['type'])] += 1
                self.animations[key] = {
                    'key': key, 'id': full, 'category': category['name'],
                    'name': raw_anim.get('name'), 'header': dict(raw_anim['header']),
                    'events': events,
                }
        for key in self.animations:
            try:
                solved = self._solve_tae(key)
            except ValueError as exc:
                self.reference_errors.append({'tae_key': key, 'error': str(exc)})
                continue
            self.hkx_to_tae[solved['hkx_key']].append(key)
        for values in self.hkx_to_tae.values():
            values.sort(key=_full_id)

        weapons = {int(row['id']): row for row in
                   _read_json(self.data_dir / "EquipParamWeapon.param.json")}
        absorps = {int(row['id']): row for row in
                   _read_json(self.data_dir / "WepAbsorpPosParam.param.json")}
        self.slot_params = {}
        for slot, equip_id in SLOT_EQUIP_IDS.items():
            w = weapons[equip_id]
            # Decode authoritative raw offsets, independent of convenience JSON fields.
            raw = bytes.fromhex(w['raw'])
            model = struct.unpack_from('<h', raw, 0xB8)[0]
            absorp_id = struct.unpack_from('<i', raw, 0x170)[0]
            ar = bytes.fromhex(absorps[absorp_id]['raw'])
            clusters = [list(struct.unpack_from('<5h', ar, 4 + 10 * i))
                        for i in range(4)]
            left_both = list(struct.unpack_from('<4h', ar, 48))
            self.slot_params[slot] = {'equip_id': equip_id, 'model_id': model,
                                     'absorp_id': absorp_id, 'clusters': clusters,
                                     'left_both': left_both}
        self.model_presence = {}
        for slot, param in self.slot_params.items():
            for i in range(4):
                key = f'{slot}{i}'
                stem = f"WP_A_{param['model_id']:04d}" + (f'_{i}' if i else '')
                path = self.data_dir / f'{stem}.json'
                present = False
                if path.exists():
                    mesh_data = _read_json(path)
                    present = any(len(m.get('pos', m.get('vertices', []))) > 0
                                  for m in mesh_data.get('meshes', []))
                if model_presence is not None:
                    if key in model_presence:
                        present = bool(model_presence[key])
                    elif slot in model_presence:
                        present = bool(model_presence[slot][i])
                self.model_presence[key] = present
        chr_path = self.data_dir / 'c0000.json'
        self.dummy_ids = ({int(d['id']) for d in _read_json(chr_path)['dummies']}
                          if chr_path.exists() else None)

    def _solve_tae(self, key, stack=()):
        if key in self._resolved:
            return self._resolved[key]
        if key in stack:
            raise ValueError('TAE reference cycle: ' + ' -> '.join((*stack, key)))
        if key not in self.animations:
            raise ValueError(f'Missing referenced TAE {key}')
        rec = self.animations[key]
        header = rec['header']
        if header.get('type') == 'ImportOtherAnim' or header.get('Type') == 1:
            target = int(header.get('ImportFromAnimID', -1))
            if target >= 0:
                ref = self._solve_tae(anim_key(target), (*stack, key))
                result = {'source_tae_key': ref['source_tae_key'],
                          'hkx_key': ref['hkx_key'], 'ref_chain': [key, *ref['ref_chain']]}
            else:
                # DSAS falls back to this entry if its ImportOtherAnim is invalid.
                result = {'source_tae_key': key, 'hkx_key': key, 'ref_chain': [key]}
        else:
            hkx_id = int(header.get('ImportHKXSourceAnimID', -1))
            # ImportsHKX redirects the binary only; this entry keeps its own events.
            hkx = anim_key(hkx_id) if header.get('ImportsHKX') and hkx_id >= 0 else key
            result = {'source_tae_key': key, 'hkx_key': hkx, 'ref_chain': [key]}
        self._resolved[key] = result
        return result

    def get_candidates(self, action_key):
        key = normalize_action_key(action_key)
        return [dict(tae_key=x, **self._resolved[x])
                for x in self.hkx_to_tae.get(key, ())]

    def resolve_action(self, action_key, *, tae_key=None, key_kind='auto'):
        if key_kind not in ('auto', 'tae', 'hkx'):
            raise ValueError("key_kind must be auto, tae, or hkx")
        key = normalize_action_key(action_key)
        candidates = self.get_candidates(key)
        chosen = None
        reason = 'no_tae'
        if tae_key is not None:
            chosen = normalize_action_key(tae_key)
            solved = self._solve_tae(chosen)
            if key_kind == 'hkx' and solved['hkx_key'] != key:
                raise ValueError(f'{chosen} uses {solved["hkx_key"]}, not requested HKX {key}')
            reason = 'explicit_tae'
        elif key_kind != 'hkx' and key in self.animations:
            chosen, reason = key, 'exact_tae'
        elif key_kind == 'tae':
            raise KeyError(f'Unknown TAE {key}')
        elif any(x['tae_key'] == key for x in candidates):
            chosen, reason = key, 'exact_hkx_and_tae'
        elif candidates:
            sources = {x['source_tae_key'] for x in candidates}
            if len(sources) == 1:
                source = next(iter(sources))
                chosen = source if source in self.hkx_to_tae[key] else candidates[0]['tae_key']
                reason = 'unique_event_source'
            else:
                reason = 'ambiguous_hkx'
        solved = self._solve_tae(chosen) if chosen else None
        return {'action_key': str(action_key), 'canonical_key': key,
                'tae_key': chosen,
                'source_tae_key': solved['source_tae_key'] if solved else None,
                'hkx_key': solved['hkx_key'] if solved else key,
                'ref_chain': solved['ref_chain'] if solved else [],
                'reason': reason, 'ambiguous': reason == 'ambiguous_hkx',
                'candidates': candidates}

    def build_action_mapping(self, action_keys, *, key_kind='hkx'):
        """One result per original action name; never drop reverse-map alternatives."""
        return {str(key): self.resolve_action(key, key_kind=key_kind) for key in action_keys}

    @staticmethod
    def _active(ev, t, prev, reverse):
        s, e = ev['start'], ev['end']
        if prev is None:
            return s <= t <= e
        enter = (prev < s <= t) or (reverse and prev >= s > t)
        leave = (prev <= e < t) or (reverse and prev > e >= t)
        return s <= t <= e or enter or leave

    @staticmethod
    def _style_at(events, t, initial):
        style = initial
        for ev in events:
            if ev['type'] == 32 and t >= ev['start']:
                style = struct.unpack_from('<i', ev['_bytes'])[0]
        return style

    def _absorp_style_at(self, events, t, initial):
        # Unsupported SDT styles do not assign Absorp at all in DSAS. Reconstruct
        # its last assigned cluster; style 0 must not arbitrarily hide weapons.
        current = initial if initial in (1, 2, 3) else 1
        boundaries = sorted({ev['start'] for ev in events
                             if ev['type'] == 32 and ev['start'] <= t})
        for time in boundaries:
            value = self._style_at(events, time, initial)
            if value in (1, 2, 3):
                current = value
        return current

    def default_dummies(self, style=1):
        if style not in (1, 2, 3):
            raise ValueError('Absorp assignment exists only for styles 1/2/3')
        result = {}
        for slot in ('R', 'L'):
            p = self.slot_params[slot]
            if style == 1:
                column = 1 if slot == 'L' else 0
                result[slot] = [r[column] for r in p['clusters']]
            elif style == 2:
                result[slot] = (list(p['left_both']) if slot == 'L'
                                else [r[4] for r in p['clusters']])
            else:
                column = 3 if slot == 'L' else 2
                result[slot] = [r[column] for r in p['clusters']]
        result['MB'] = [149, 149, -1, -1]
        if 'GH' in self.slot_params:result['GH'] = [-1, -1, -1, -1]
        return result

    def get_state(self, action_key, t, prev_t=None, *, tae_key=None, key_kind='auto',
                  start_weapon_style=None, simulate_reverse=False, previous_state=None):
        t = _f32(t)
        prev = _f32(prev_t) if prev_t is not None else None
        if not math.isfinite(t) or (prev is not None and not math.isfinite(prev)):
            raise ValueError('Times must be finite seconds')
        resolution = self.resolve_action(action_key, tae_key=tae_key, key_kind=key_kind)
        if resolution['ambiguous']:
            raise AmbiguousAnimationError(resolution)
        source_key = resolution['source_tae_key']
        events = self.animations[source_key]['events'] if source_key else []
        initial = self.start_weapon_style if start_weapon_style is None else int(start_weapon_style)
        style = self._style_at(events, t, initial)
        absorp_style = self._absorp_style_at(events, t, initial)
        if style not in (1, 2, 3) and previous_state is not None:
            absorp_style = previous_state['absorp_style']
        dummies = self.default_dummies(absorp_style)
        hidden = {slot: [False] * 4 for slot in SLOT_EQUIP_IDS}
        overrides = {slot: None for slot in SLOT_EQUIP_IDS}
        face607 = []
        applied = []
        ignored = []
        for ev in events:
            typ, raw = int(ev['type']), ev['_bytes']
            if typ == 32:
                if t >= ev['start']:
                    applied.append({'index': ev['index'], 'type': 32,
                                    'style': struct.unpack_from('<i', raw)[0]})
                continue
            if typ not in (607, 710, 712, 715):
                continue
            if not self._active(ev, t, prev, simulate_reverse):
                continue
            detail = {'index': ev['index'], 'type': typ,
                      'start': ev['start'], 'end': ev['end']}
            if typ == 712:
                ignored.append(dict(detail, reason='Not processed for SDT'))
            elif typ == 715:
                model_type = raw[0]
                models = list(struct.unpack_from('<4i', raw, 4))
                slot = MODEL_TYPE_SLOTS.get(model_type)
                if slot is None:
                    ignored.append(dict(detail, reason='Slot outside R/L/MB', model_type=model_type))
                    continue
                dummies[slot] = models  # Last event in original TAE order wins.
                overrides[slot] = ev['index']
                applied.append(dict(detail, slot=slot, dummies=models))
            elif typ == 710:
                # Deliberately preserve RC6.1's crossed byte2/byte3 implementation.
                if raw[0]:
                    hidden['L'] = [True] * 4
                if raw[1]:
                    hidden['R'] = [True] * 4
                if raw[2]:
                    hidden['R'][0] = True
                if raw[3]:
                    hidden['L'][0] = True
                applied.append(dict(detail, flags=list(raw[:4])))
            else:  # 607: report all active requests; DSAS uses the last one.
                mode, value, a, b = struct.unpack_from('<iiff', raw)
                if mode != 0:
                    ignored.append(dict(detail, reason='607 mode is not zero', mode=mode))
                    continue
                value = max(0, min(15, value))
                span = _f32(ev['end'] - ev['start'])
                if span == 0:
                    s = float('nan') if t == ev['start'] else (1.0 if t > ev['start'] else 0.0)
                else:
                    s = max(0.0, min(1.0, _f32(_f32(t - ev['start']) / span)))
                weight = _f32(a + _f32(_f32(b - a) * s))
                request = dict(detail, animation=anim_key(790000 + value * 10),
                               input_value=value, interpolated_weight=weight,
                               weight=1.0 if weight > 0 else 0.0,
                               looping=True, clear_on_end=False)
                face607.append(request)
                applied.append(request)
        slots, models, visibility = {}, {}, {}
        for slot, param in self.slot_params.items():
            slots[slot] = []
            visibility[slot] = []
            for i, dummy in enumerate(dummies[slot]):
                key = f'{slot}{i}'
                exists = dummy >= 0 and (self.dummy_ids is None or dummy in self.dummy_ids)
                available = self.model_presence[key]
                visible = available and exists and not hidden[slot][i]
                model = {'slot': slot, 'model': i, 'dummy': dummy, 'visible': visible,
                         'has_geometry': available, 'hidden_by_tae': hidden[slot][i],
                         'hidden_by_absorp': not exists, 'override_event_index': overrides[slot],
                         'part': f"WP_A_{param['model_id']:04d}" + (f'_{i}' if i else '')}
                slots[slot].append(model)
                models[key] = model
                visibility[slot].append(visible)
        return {'resolution': resolution, 'time': t, 'prev_time': prev,
                'weapon_style': style, 'weapon_style_name': STYLE_NAMES.get(style, str(style)),
                'absorp_style': absorp_style, 'dummies': dummies, 'visibility': visibility,
                'slots': slots, 'models': models, 'face607': face607,
                'face': face607[-1] if face607 else None,
                'applied_events': applied, 'ignored_events': ignored}

    def statistics(self):
        return {'tae_animation_count': len(self.animations),
                'header_types': dict(collections.Counter(a['header'].get('type')
                                      for a in self.animations.values())),
                'event_counts': {str(k): self.event_counts[k] for k in (32, 607, 710, 712, 715)},
                'resolved_tae_count': len(self._resolved),
                'hkx_key_count': len(self.hkx_to_tae),
                'hkx_with_multiple_tae_candidates': sum(len(v) > 1 for v in self.hkx_to_tae.values()),
                'ambiguous_hkx_without_exact_tae': sum(self.resolve_action(k, key_kind='hkx')['ambiguous']
                                                     for k in self.hkx_to_tae),
                'reference_errors': self.reference_errors,
                'slot_params': self.slot_params, 'model_presence': self.model_presence,
                'defaults_by_style': {str(s): self.default_dummies(s) for s in (1, 2, 3)}}


_DEFAULT_DB = None


def get_database():
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        _DEFAULT_DB = EventStateDatabase()
    return _DEFAULT_DB


def get_state(action_key, t, prev_t=None, **kwargs):
    return get_database().get_state(action_key, t, prev_t, **kwargs)


def get_candidates(action_key):
    return get_database().get_candidates(action_key)


def resolve_action(action_key, **kwargs):
    return get_database().resolve_action(action_key, **kwargs)


def build_action_mapping(action_keys, **kwargs):
    return get_database().build_action_mapping(action_keys, **kwargs)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?')
    parser.add_argument('time', nargs='?', type=float, default=0.0)
    parser.add_argument('--prev', type=float)
    parser.add_argument('--tae')
    parser.add_argument('--key-kind', choices=('auto', 'tae', 'hkx'), default='auto')
    args = parser.parse_args()
    result = (get_state(args.action, args.time, args.prev, tae_key=args.tae, key_kind=args.key_kind)
              if args.action else get_database().statistics())
    print(json.dumps(result, indent=2, ensure_ascii=False))
