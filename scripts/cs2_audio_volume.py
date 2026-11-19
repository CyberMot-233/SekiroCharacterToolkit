"""Independent per-animation CS2 soundevent volumes; no audio/DMX rebake."""
import argparse, copy, datetime, hashlib, json, math, re, shutil, subprocess
from pathlib import Path
from cs2_common import read, save, kv, SoundEvent, cs_root, compile_resource
from cs2_kvtext import loads, TOKEN

MAX_VOLUME = 10.0

def volume(value):
    if isinstance(value, bool):
        raise ValueError('音量必须是 0–10 的数字')
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= MAX_VOLUME:
        raise ValueError('音量必须在 0–10 之间（0 静音，1 原始音量）')
    return result

def read_volumes(path):
    data = read(path) if path else {}
    if not isinstance(data, dict):
        raise ValueError('音量配置必须是 动作名称:音量 的 JSON 对象')
    return {str(k): volume(v) for k, v in data.items()}

def alias_name(model, animation, original):
    # Full source event name participates, so unrelated events cannot collide.
    digest = hashlib.sha256((animation + '\0' + original).encode()).hexdigest()[:24]
    return f'sekiro.{model}.sctvol_{digest}'

def alias_block(text, model, additions):
    begin, end = f'// SCT AUDIO VOLUME BEGIN {model}', f'// SCT AUDIO VOLUME END {model}'
    pattern = re.compile(re.escape(begin) + r'\n.*?' + re.escape(end), re.S)
    matches = list(pattern.finditer(text))
    if len(matches) > 1 or ((begin in text or end in text) and not matches):
        raise ValueError('音量事件标记不完整或重复，保留原件')
    definitions = loads('{\n' + matches[0].group().split('\n', 1)[1].rsplit(end, 1)[0] + '\n}') if matches else {}
    definitions.update(additions)
    content = begin + '\n' + '\n'.join(json.dumps(k) + ' = ' + kv(v) for k, v in sorted(definitions.items())) + '\n' + end
    if matches:
        return text[:matches[0].start()] + content + text[matches[0].end():]
    at = text.rfind('}')
    if at < 0:
        raise ValueError('声音事件文件缺少结束括号')
    return text[:at] + '\n' + content + '\n' + text[at:]

def object_fields(text):
    """Scalar fields and exact spans, preserving all unrelated KV3 bytes/types."""
    tokens = [m for m in TOKEN.finditer(text) if not m.group().isspace() and not m.group().startswith(('//', '<!--'))]
    stack, objects = [], []
    for i, token in enumerate(tokens):
        t = token.group()
        if t == '{':
            stack.append({'start': token.start(), 'fields': {}, 'parent': stack[-1] if stack else None})
        elif t == '}':
            obj = stack.pop(); obj['end'] = token.end(); objects.append(obj)
        elif stack and i + 2 < len(tokens) and tokens[i + 1].group() == '=':
            key = json.loads(t) if t.startswith('"') else t
            j = i + 2; start = tokens[j].start()
            if j + 2 < len(tokens) and tokens[j + 1].group() == ':':
                j += 2
            scalar = tokens[j].group()
            if scalar not in ('{', '['):
                try: value = json.loads(scalar)
                except ValueError: value = scalar
                stack[-1]['fields'][key] = (value, start, tokens[j].end())
    return objects

def animation_sounds(text):
    objects = object_fields(text); result = {}
    def val(obj, key): return obj['fields'].get(key, (None,))[0]
    children = {}
    for obj in objects:
        if obj['parent'] is not None: children.setdefault(id(obj['parent']), []).append(obj)
        if val(obj, '_class') == 'AnimFile':
            name = val(obj, 'name')
            if name in result: raise ValueError('重复动作名称：' + name)
            result[name] = []
    for event in objects:
        if val(event, '_class') != 'AnimEvent' or val(event, 'event_class') != 'AE_CL_PLAYSOUND_ATTACHMENT': continue
        parent = event['parent']
        while parent and val(parent, '_class') != 'AnimFile': parent = parent['parent']
        if parent is None: continue
        name = val(parent, 'name')
        keys = [o for o in children.get(id(event), []) if 'name' in o['fields']]
        if len(keys) != 1: raise ValueError('无法唯一定位声音事件名称：' + name)
        result[name].append(keys[0]['fields']['name'])
    return result

def inspect(addon, model):
    addon = Path(addon); base = addon / f'rawmodels/sekiro/characters/{model}'
    export = read(base / 'compile_export.json')
    vmdl = addon / f'models/sekiro/characters/{model}/{model}.vmdl'
    manifest = addon / 'soundevents/soundevents_addon.vsndevts'
    sounds = animation_sounds(vmdl.read_text('utf-8-sig')); definitions = loads(manifest.read_text('utf-8-sig'))
    clips = []
    for action in export['actions']:
        if action['name'] not in sounds: continue
        refs = sounds[action['name']]; values = []
        for key, _, _ in refs:
            if key not in definitions: raise ValueError('声音事件定义不存在：' + key)
            v = definitions[key].get('volume', 1.0)
            if not isinstance(v, (int, float)): raise ValueError('不支持非标量音量：' + key)
            values.append(volume(v))
        unique = sorted(set(values))
        clips.append(dict(source=action['source'], name=action['name'], events=len(refs), volume=unique[0] if len(unique) == 1 else None, mixed=len(unique) > 1))
    return dict(clips=clips, vmdl=str(vmdl), manifest=str(manifest))

def plan(text, manifest_text, model, actions, volumes):
    sounds = animation_sounds(text); definitions = loads(manifest_text)
    records = {a['source']: a for a in actions}
    unknown = set(volumes) - set(records)
    if unknown: raise ValueError('所选动作不在已完成列表：' + ', '.join(sorted(unknown)))
    edits, additions, report = [], {}, []
    prefix = f'sekiro.{model}.sctvol_'
    for source, gain in volumes.items():
        gain = volume(gain); animation = records[source]['name']
        if animation not in sounds: raise ValueError('VMDL 不包含动作：' + animation)
        for original, start, end in sounds[animation]:
            if original not in definitions: raise ValueError('声音事件定义不存在：' + original)
            alias = original if original.startswith(prefix) else alias_name(model, animation, original)
            definition = copy.deepcopy(definitions[original]); definition['volume'] = gain
            additions[alias] = definition
            edits.append((start, end, 'soundevent:' + json.dumps(alias)))
        report.append(dict(source=source, name=animation, volume=gain, events=len(sounds[animation])))
    updated = text
    for start, end, value in sorted(edits, reverse=True): updated = updated[:start] + value + updated[end:]
    registration = alias_block(manifest_text, model, additions) if additions else manifest_text
    # The only permitted semantic difference in VMDL is soundevent names.
    def protected(doc):
        doc = copy.deepcopy(doc)
        def visit(x):
            if isinstance(x, dict):
                if x.get('_class') == 'AnimEvent' and x.get('event_class') == 'AE_CL_PLAYSOUND_ATTACHMENT': x['event_keys']['name'] = '<audio-name>'
                for v in x.values(): visit(v)
            elif isinstance(x, list):
                for v in x: visit(v)
        visit(doc); return doc
    if protected(loads(text)) != protected(loads(updated)): raise RuntimeError('非音频模型属性发生变化')
    parsed = loads(registration)
    if any(parsed[k] != v for k, v in definitions.items() if k not in additions): raise RuntimeError('未选择声音事件发生变化')
    return updated, registration, report

def apply_export(events, definitions, actions, volumes, model):
    """Use identical independent aliases during first-time conversion."""
    for action in actions:
        source = action['source']
        if source not in volumes: continue
        gain = volume(volumes[source])
        for event in events.get(source, []):
            old = event['event_keys']['name']; alias = alias_name(model, action['name'], old)
            definitions[alias] = {**definitions[old], 'volume': gain}
            event['event_keys']['name'] = SoundEvent(alias)

def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def verify_compiled(addon, model, source_text, registration):
    root = cs_root(addon); game = root / 'game/csgo_addons' / addon.name
    exe = root / 'game/bin/win64/resourceinfo.exe'
    def dump(path, block):
        result = subprocess.run([str(exe), '-i', str(path), '-b', block, '-baremode', '-maxelements', '99999999'], capture_output=True, encoding='utf-8', errors='replace', check=True)
        return loads(result.stdout)
    definitions = loads(registration)
    compiled = dump(game / 'soundevents/soundevents_addon.vsndevts_c', 'DATA')
    source = animation_sounds(source_text)
    anim = dump(game / f'models/sekiro/characters/{model}/{model}.vmdl_c', 'ANIM')
    actions = {a['m_name']: a for a in anim['m_animArray']}
    issues = []; count = 0
    for name, events in source.items():
        expected = [e[0] for e in events]
        if name not in actions: issues.append('Missing compiled animation: ' + name); continue
        actual = [e['m_EventData']['name'] for e in actions[name]['m_eventArray'] if e.get('m_sEventName') == 'AE_CL_PLAYSOUND_ATTACHMENT']
        if expected != actual: issues.append('Compiled soundevent names/order mismatch: ' + name)
        for event in expected:
            count += 1
            definition = compiled.get(event)
            if not definition: issues.append('Missing compiled event: ' + event); continue
            if not math.isclose(float(definition.get('volume', 1)), float(definitions[event].get('volume', 1)), rel_tol=1e-6, abs_tol=1e-6): issues.append('Compiled volume mismatch: ' + event)
            if definition.get('vsnd_files_track_01') != definitions[event].get('vsnd_files_track_01'): issues.append('Compiled audio file mismatch: ' + event)
    return dict(passed=not issues, events=count, animations=len(source), issues=issues)

def update(addon, model, volumes, compile=False):
    addon = Path(addon).resolve(); root = cs_root(addon)
    base = addon / f'rawmodels/sekiro/characters/{model}'; reports = base / 'reports'
    if not (base / 'sct_owner.json').is_file(): raise ValueError('目标不是本工具管理的角色资源')
    export = read(base / 'compile_export.json')
    if not export.get('passed'): raise ValueError('已完成动作校验未通过')
    vmdl = addon / f'models/sekiro/characters/{model}/{model}.vmdl'; manifest = addon / 'soundevents/soundevents_addon.vsndevts'
    text = vmdl.read_text('utf-8-sig'); original = manifest.read_text('utf-8-sig')
    updated, registration, changes = plan(text, original, model, export['actions'], volumes)
    if not changes: raise ValueError('没有选择需要设置音量的动作')
    protected_paths = [addon / a['file'] for a in export['actions'] + export['mesh_groups']]
    protected_paths += list((addon / f'sounds/sekiro/characters/{model}').glob('*.wav'))
    protected = {str(p): sha(p) for p in protected_paths}
    backup = base / 'backups' / ('audio_volume_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True); reports.mkdir(parents=True, exist_ok=True)
    game = root / 'game/csgo_addons' / addon.name
    for p in (vmdl, manifest):
        shutil.copy2(p, backup / p.name)
        compiled = game / (str(p.relative_to(addon)) + '_c')
        if compiled.exists(): shutil.copy2(compiled, backup / compiled.name)
    report = dict(passed=False, version='0.10.9', changes=changes, backup=str(backup), compile_requested=compile, compiled=[], runtime_listening='not_run')
    try:
        if updated != text: vmdl.write_text(updated, 'utf-8')
        if registration != original: manifest.write_text(registration, 'utf-8')
        if compile:
            for target in (manifest, vmdl):
                item = compile_resource(addon, target, reports / ('audio_volume_' + target.stem + '.log'))
                report['compiled'].append(item)
                if not item['passed']: raise RuntimeError('音量编译失败：' + item['log'])
            report['compiled_validation'] = verify_compiled(addon, model, updated, registration)
            if not report['compiled_validation']['passed']: raise RuntimeError('编译声音事件回读不一致：' + str(report['compiled_validation']['issues'][:3]))
        report['protected_files_unchanged'] = all(sha(p) == h for p, h in protected.items())
        if not report['protected_files_unchanged']: raise RuntimeError('DMX 或原始音频被改写')
        actual = {a['source']: a for a in inspect(addon, model)['clips']}
        for source, gain in volumes.items():
            if actual[source]['events'] and actual[source]['volume'] != volume(gain): raise RuntimeError('音量回读不匹配：' + source)
        report.update(passed=True, status='compiled_offline' if compile else 'source_ready', vmdl_sha256=sha(vmdl), manifest_sha256=sha(manifest))
    except Exception as e:
        report.update(error=str(e), status='failed')
        save(reports / 'audio_volume.json', report); raise
    settings_path = base / 'audio_volumes.json'
    saved = read_volumes(settings_path) if settings_path.exists() else {}
    saved.update({k: volume(v) for k, v in volumes.items()}); save(settings_path, saved)
    save(reports / 'audio_volume.json', report)
    print('CS2_AUDIO_VOLUME', len(changes), '动作；无需重烘/重转音频；', reports / 'audio_volume.json', flush=True)
    return report

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--addon', required=True, type=Path); ap.add_argument('--name', required=True)
    ap.add_argument('--volumes', type=Path); ap.add_argument('--inspect', type=Path); ap.add_argument('--compile', action='store_true')
    a = ap.parse_args()
    if not re.fullmatch('[a-z][a-z0-9_]*', a.name): raise ValueError('模型名格式不正确')
    if a.inspect: save(a.inspect, inspect(a.addon, a.name))
    else: update(a.addon, a.name, read_volumes(a.volumes), a.compile)

if __name__ == '__main__': main()
