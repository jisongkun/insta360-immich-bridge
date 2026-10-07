"""One explicit bridge request, using the upstream conversion worker (GPL-3.0)."""
import json
import sys
from pathlib import Path
from bridge.legacy import load


def main():
    manifest=json.loads(Path(sys.argv[1]).read_text())
    root=Path(manifest['work_dir'])
    legacy=load()
    legacy.configure_logging('INFO')
    legacy.configure_paths(str(root),str(root/'raw'),str(root/'output'),str(root/'conversion.db'))
    controller=legacy.AutoStitcher(debug=False)
    profile=manifest['profile']
    controller.set_stitch_settings(profile['output_size'],profile['bitrate'],profile['stitch_type'],
                                   profile['auto_resolution'],profile['original_bitrate'])
    for key in ('enable_h265','enable_flowstate','enable_directionlock','enable_stitchfusion','disable_cuda'):
        setattr(controller,key,profile[key])
    controller.metadata_timestamp=manifest['capture_time']
    controller.sdk_executable=manifest['sdk_executable']
    controller.model_root=manifest['model_root']
    job=controller.db.insert_job(timestamp=manifest['timestamp'],final_file=manifest['output'],
                                source_files=manifest['sources'],status=legacy.STATUS_UNPROCESSED,
                                expected_size=controller._calculate_expected_size(manifest['sources']))
    controller._run_job(job)
    result=controller.db.fetch_job(job)
    Path(manifest['result']).write_text(json.dumps({'status':result['status'],'output':manifest['output']}))
    return 0 if result['status']==legacy.STATUS_PROCESSED else 1


if __name__=='__main__':sys.exit(main())
