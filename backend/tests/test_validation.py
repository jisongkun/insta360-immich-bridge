import subprocess
import pytest
from bridge.validation import validate
from bridge.discovery import snapshot, hashes


def test_media_without_spherical_metadata_cannot_upload(tmp_path):
    path=tmp_path/'output.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=size=128x64:rate=10','-t','1','-c:v','libx264',str(path)],check=True)
    source=tmp_path/'source.insv';source.write_bytes(b'original')
    group={'kind':'video','files':[{'path':str(source),'stat':snapshot(source),'sha256':hashes(source)[0]}]}
    with pytest.raises(ValueError,match='spherical'):validate(path,group,{'output_size':'128x64'},source_probe={'duration':1,'fps':10,'audio':False})
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Source'):validate(path,group,{'output_size':'128x64'},source_probe={'duration':1,'fps':10,'audio':False})


def test_real_spherical_injection_decode_and_media_guards(tmp_path):
    from spatialmedia import metadata_utils
    source=tmp_path/'source.insv';source.write_bytes(b'original')
    group={'kind':'video','files':[{'path':str(source),'stat':snapshot(source),'sha256':hashes(source)[0]}]}
    plain=tmp_path/'plain.mp4';path=tmp_path/'360.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=size=128x64:rate=10','-t','1','-c:v','libx264',str(plain)],check=True)
    metadata=metadata_utils.Metadata();metadata.video=metadata_utils.generate_spherical_xml('equirectangular')
    metadata_utils.inject_metadata(str(plain),str(path),metadata,lambda *_:None)
    profile={'output_size':'128x64'}
    src={'duration':1,'fps':10,'audio':False}
    assert validate(path,group,profile,source_probe=src)['width']==128
    with pytest.raises(ValueError,match='duration'):validate(path,group,profile,source_probe={**src,'duration':3})
    with pytest.raises(ValueError,match='audio'):validate(path,group,profile,source_probe={**src,'audio':True})
    with pytest.raises(ValueError,match='dimensions'):validate(path,group,{'output_size':'256x128'},source_probe=src)
    with pytest.raises(ValueError,match='capture date'):validate(path,{**group,'capture_time':'2026-10-07T12:00:00+08:00'},profile,source_probe=src)
