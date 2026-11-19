"""Re-decode source spline blocks and rebuild a NEW sibling job; original stays untouched."""
import argparse, datetime, json, os, shutil, subprocess, sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('package',type=Path);ap.add_argument('--worker',required=True);ap.add_argument('--blender',required=True);ap.add_argument('--out',type=Path);ap.add_argument('--helper-visibility',choices=['visible','hidden'],default='visible');args=ap.parse_args()
    source=args.package.resolve();pkg=json.loads((source/'package.json').read_text(encoding='utf-8-sig'))
    dest=(args.out or source.with_name(source.name+'_endfix_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))).resolve()
    if dest==source or dest.is_relative_to(source):raise ValueError('Repair output must be a new sibling folder')
    dest.mkdir(parents=True,exist_ok=False);scripts=Path(__file__).resolve().parent
    report={'passed':False,'source_job':str(source),'output_job':str(dest),'original_unchanged':True,
            'mode':'rebuild from source into new copy; preserve action selection/root-axis settings, not manual pose edits', 'errors':[]}
    try:
        # Never copy stale success reports; regenerate authoritative validation.
        folders={'models','animations','textures','raw','source_native','equipment','audio'}
        for f in source.iterdir():
            if f.is_dir() and f.name in folders:
                shutil.copytree(f,dest/f.name,ignore=shutil.ignore_patterns('backups','_internal','*.blend','*.blend1','*.log'))
            elif f.is_file() and f.name in {'package.json','tae.json','source_manifest.json','weapon_motion.json','selected_actions.json','root_motion_options.json'}:shutil.copy2(f,dest/f.name)
        def run(cmd):
            print('RUN',*[str(x) for x in cmd],flush=True)
            subprocess.run([str(x) for x in cmd],check=True)
        def blend(script,*argv):run([args.blender,'--background','--factory-startup','--disable-autoexec','--threads','4','--python-exit-code','1','--python',scripts/'blender_bootstrap.py','--python',scripts/script,'--',*argv])
        state_file=dest/'animation_repair_state.json';blend('animation_repair_state.py','capture',source,state_file)
        state=json.loads(state_file.read_text(encoding='utf-8'))
        run([args.worker,'resample','--root',pkg.get('root',str(source)),'--package',dest])
        run([sys.executable,scripts/'prepare_textures.py',dest]);blend('build_character.py',dest)
        if state['clean']:blend('clean_bones.py',dest,'--no-backup')
        if state['hierarchy']:blend('restore_hierarchy.py',dest,'--no-backup')
        blend('animation_repair_state.py','restore',dest,state_file)
        blend('helper_visibility.py',dest,'--visibility',args.helper_visibility,'--no-backup')
        blend('verify_saved.py',dest);blend('verify_appearance.py',dest)
        sampling=json.loads((dest/'sampling_report.json').read_text(encoding='utf-8-sig'))
        report.update(passed=True,sampling=sampling)
    except Exception as e:
        report['errors'].append(str(e));raise
    finally:
        (dest/'animation_endpoint_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ANIMATION_REPAIRED',dest,flush=True)
if __name__=='__main__':main()
