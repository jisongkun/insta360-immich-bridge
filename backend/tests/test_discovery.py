import time
from pathlib import Path
import pytest
from bridge.config import BridgeConfig
from bridge.store import Store
from bridge.discovery import discover_folders, discover_immich, resolve_original


def config(tmp_path,root):
    return BridgeConfig({'state_dir':str(tmp_path/'state'),'work_dir':str(tmp_path/'work'),'folders':[str(root)],'stable_seconds':1})


def test_recursive_stability_pairing_and_content_dedup(tmp_path,monkeypatch):
    root=tmp_path/'raw';root.mkdir(); nested=root/'day';nested.mkdir()
    p=nested/'VID_20261007_120000_00_001.INSV';p.write_bytes(b'one')
    store=Store(tmp_path/'state.db');cfg=config(tmp_path,root)
    monkeypatch.setattr('bridge.discovery.stream_count',lambda path:1)
    assert discover_folders(cfg,store,10)==[]
    assert discover_folders(cfg,store,12)==[]
    second=nested/'VID_20261007_120000_10_001.INSV';second.write_bytes(b'two')
    assert discover_folders(cfg,store,13)==[]
    groups=discover_folders(cfg,store,15)
    assert len(groups)==1 and len(groups[0]['files'])==2
    copy=root/'copy';copy.mkdir()
    for f in (p,second): (copy/f.name).write_bytes(f.read_bytes())
    hidden=root/'.hidden';hidden.mkdir();(hidden/p.name).write_bytes(b'ignored')
    (root/'link').symlink_to(nested,target_is_directory=True)
    discover_folders(cfg,store,16)
    assert len(discover_folders(cfg,store,18))==1
    p.write_bytes(b'changed')
    assert len(discover_folders(cfg,store,19))==1 # only stable duplicate


def test_mapping_and_missing_mount(tmp_path):
    root=tmp_path/'raw';root.mkdir()
    mappings=[{'from':'/data','to':str(root)}]
    with pytest.raises(ValueError): resolve_original('/data/../escape',mappings)
    with pytest.raises(ValueError): resolve_original('/other/file.insv',mappings)
    (root/'link').symlink_to(tmp_path)
    with pytest.raises(ValueError): resolve_original('/data/link/file.insv',mappings)
    assert resolve_original('/data/a.insv',mappings)==root/'a.insv'
    with pytest.raises(FileNotFoundError): discover_folders(config(tmp_path,tmp_path/'missing'),Store(tmp_path/'s.db'),10)


def test_incremental_watermark_only_after_all_pages(tmp_path):
    class Client:
        base='http://server/api'; server_time=1000
        def __init__(self):self.calls=[];self.fail=False
        def search(self,filter,cursor=None):
            self.calls.append((filter,cursor))
            if cursor and self.fail: raise RuntimeError('network')
            return {'items':[], 'nextCursor':'next' if cursor is None else None}
    client=Client();store=Store(tmp_path/'s.db');cfg=config(tmp_path,tmp_path/'raw')
    cfg.data['folders']=[]; store.set('target','owner')
    client.fail=True
    with pytest.raises(RuntimeError):discover_immich(client,cfg,store)
    assert store.get('watermark:owner') is None
    client.fail=False;discover_immich(client,cfg,store)
    assert store.get('watermark:owner')==1000
    client.server_time=1200;discover_immich(client,cfg,store)
    filter=client.calls[-2][0]
    assert 'or' in filter and 'createdAt' in filter['or'][0]
    assert 'takenAt' not in str(filter)
