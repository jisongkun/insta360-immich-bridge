from pathlib import Path
import pytest
from bridge.legacy import load


def controller(tmp_path):
    legacy=load()
    legacy.configure_paths(str(tmp_path),str(tmp_path/'raw'),str(tmp_path/'out'))
    return legacy.AutoStitcher(debug=False)


def test_new_sdk_command_keeps_existing_features(tmp_path):
    c=controller(tmp_path)
    c.sdk_executable='/opt/MediaSDK-3.1.5-linux/bin/MediaSDKTest'
    c.model_root=str(tmp_path/'models');Path(c.model_root).mkdir()
    command=c.build_sdk_command(['one.insv','two.insv'],'out.mp4','5760x2880')
    assert command[0]==c.sdk_executable
    assert '-disable_cuda' not in command
    assert '-enable_flowstate' in command and '-enable_h265_encoder' in command
    assert command[command.index('-model_root_dir')+1].endswith('/')
    c.disable_cuda=True
    assert '-disable_cuda' in c.build_sdk_command(['one.insv'],'out.mp4','5760x2880')
    c.stitch_type='aistitch';c.model_root=str(tmp_path/'absent')
    with pytest.raises(ValueError):c.build_sdk_command(['one.insv'],'out.mp4','5760x2880')


def test_gateway_request_uses_unique_workspace(tmp_path):
    from bridge.converter import Converter
    converter=Converter()
    group={'id':'source','files':[{'path':'/readonly/source.insv'}],'timestamp':'20261007_120000','kind':'video','capture_time':'2026-10-07T12:00:00+08:00'}
    manifest=converter.manifest('job',group,{'output_size':'5760x2880'},tmp_path)
    assert manifest['sources']==['/readonly/source.insv']
    assert Path(manifest['output']).parent==tmp_path
    assert manifest['debug'] is False
