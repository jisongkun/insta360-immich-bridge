import json
import subprocess
from pathlib import Path
from .discovery import snapshot,hashes


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=120)
    if result.returncode:raise ValueError('Media probe failed')
    data=json.loads(result.stdout)
    video=next((s for s in data['streams'] if s['codec_type']=='video'),None)
    if video is None:raise ValueError('No video/image stream')
    fps=video.get('avg_frame_rate','0/1').split('/')
    fps=float(fps[0])/float(fps[1]) if float(fps[1]) else 0
    audio=[s for s in data['streams'] if s['codec_type']=='audio']
    return {'raw':data,'width':video['width'],'height':video['height'],'fps':fps,
            'duration':float(data.get('format',{}).get('duration',video.get('duration',0))),
            'audio':bool(audio),'audio_durations':[float(s['duration']) for s in audio if 'duration' in s]}


def validate(path,group,profile,source_probe=None):
    for file in group['files']:
        if snapshot(file['path'])!=file['stat'] or hashes(file['path'])[0]!=file['sha256']:
            raise ValueError('Source changed during conversion')
    output=probe(path)
    if group['kind']=='photo':
        result=subprocess.run(['exiftool','-j','-ProjectionType','-UsePanoramaViewer',str(path)],capture_output=True,text=True,timeout=120)
        tags=json.loads(result.stdout)[0] if result.returncode==0 else {}
        spherical=tags.get('ProjectionType')=='equirectangular' and str(tags.get('UsePanoramaViewer')).lower() in ('true','1')
    else:
        # ffprobe exposes v2 spherical mapping; the upstream injector uses the v1 XML UUID.
        spherical=any(d.get('side_data_type')=='Spherical Mapping' and d.get('projection')=='equirectangular' for s in output['raw']['streams'] for d in s.get('side_data_list',[]))
        if not spherical:
            from spatialmedia import metadata_utils
            import contextlib,io
            with contextlib.redirect_stdout(io.StringIO()):
                metadata=metadata_utils.parse_metadata(str(path),lambda *_:None)
            spherical=bool(metadata and getattr(metadata,'video',None) and any(v and v.get('Spherical')=='true' and v.get('ProjectionType')=='equirectangular' for v in metadata.video.values()))
        if not spherical:raise ValueError('Missing spherical panorama metadata')
    if not spherical:raise ValueError('Missing spherical panorama metadata')
    if output['width']!=2*output['height']:raise ValueError('Output is not 2:1')
    if group['kind']=='video':
        source=source_probe or probe(group['files'][0]['path'])
        if not profile.get('auto_resolution') and f"{output['width']}x{output['height']}"!=profile['output_size']:raise ValueError('Output dimensions differ')
        if source['duration']<=0 or abs(output['duration']-source['duration'])>max(0.5,2/max(source['fps'],1)):raise ValueError('Output duration differs')
        if source['audio'] and not output['audio']:raise ValueError('Source audio was lost')
        if any(abs(d-output['duration'])>0.5 for d in output['audio_durations']):raise ValueError('Audio/video duration differs')
        for file in group['files'][1:]:
            if abs(probe(file['path'])['duration']-source['duration'])>0.5:raise ValueError('Lens durations differ')
        from datetime import datetime
        if group.get('capture_time'):
            actual=output['raw'].get('format',{}).get('tags',{}).get('creation_time')
            if not actual or abs((datetime.fromisoformat(actual.replace('Z','+00:00'))-datetime.fromisoformat(group['capture_time'])).total_seconds())>1:
                raise ValueError('Output capture date differs')
    result=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],capture_output=True,timeout=None)
    if result.returncode:raise ValueError('Output is not completely decodable')
    return output
