import threading
import pytest
from bridge.config import BridgeConfig, profile_hash
from bridge.store import Store


def test_receipt_identity_and_claims_survive_restart(tmp_path):
    path = tmp_path / 'state.db'
    store = Store(path)
    first = store.enqueue({'id':'source'}, {'output_size':'5760x2880'}, 'target')
    assert store.enqueue({'id':'source'}, {'output_size':'5760x2880'}, 'target') == first
    assert store.enqueue({'id':'source'}, {'output_size':'3840x1920'}, 'target') != first
    assert store.enqueue({'id':'source'}, {'output_size':'5760x2880'}, 'other') != first
    assert store.enqueue({'id':'source'}, {'output_size':'5760x2880'}, 'target', force=True) != first
    results=[]
    threads=[threading.Thread(target=lambda: results.append(store.claim(first))) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(results) == [False, True]
    store.update(first, stage='done', asset_id='asset', verified=True)
    assert Store(path).job(first)['verified'] is True


def test_profiles_and_public_settings(tmp_path):
    config=BridgeConfig({'state_dir':str(tmp_path/'state'),'work_dir':str(tmp_path/'work'), 'api_key':'not-allowed'})
    with pytest.raises(ValueError): config.validate()
    config=BridgeConfig({'state_dir':str(tmp_path/'state'),'work_dir':str(tmp_path/'work')})
    assert config.public()['automatic'] is False
    assert config.public()['interval'] == 60
    with pytest.raises(ValueError): config.changed({'interval':0})
    assert profile_hash({'output_size':'5760x2880','bitrate':'100'}) != profile_hash({'output_size':'5760x2880','bitrate':'200'})


def test_events_and_recovery(tmp_path):
    store=Store(tmp_path/'state.db')
    job=store.enqueue({'id':'source'}, {}, 'target')
    store.claim(job)
    store.update(job, stage='uploading', output_sha256='proof')
    store.recover()
    assert not store.job(job)['claimed']
    assert store.job(job)['stage']=='uploading'
    store.event(job,'uploading','retained')
    assert store.events(job,after=0)[0]['message']=='retained'
