import hashlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from bridge.immich import ImmichClient, ImmichError

@pytest.fixture
def server():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def handle_request(self):
            size=int(self.headers.get('Content-Length',0)); body=self.rfile.read(size)
            calls.append((self.command,self.path,dict(self.headers),body))
            if self.path=='/api/assets/bad':
                self.send_response(401); self.end_headers(); self.wfile.write(b'secret must not leak'); return
            value={}
            if self.path=='/api/users/me': value={'id':'owner'}
            elif self.path=='/api/server/about': value={'version':'3.2.4'}
            elif self.path=='/api/assets/bulk-upload-check': value={'results':[{'action':'reject','reason':'duplicate','assetId':'existing','isTrashed':False}]}
            elif self.path=='/api/assets': value={'status':'created','id':'new'}
            elif self.path=='/api/search/metadata': value={'assets':{'items':[],'nextCursor':None}}
            if self.path.endswith('/original'):
                data=b'original'
            else: data=json.dumps(value).encode()
            self.send_response(200); self.send_header('Date','Wed, 07 Oct 2026 08:00:00 GMT'); self.end_headers(); self.wfile.write(data)
        do_GET=do_POST=do_PUT=do_DELETE=handle_request
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
    yield f'http://127.0.0.1:{http.server_port}',calls
    http.shutdown();http.server_close();t.join()

def test_stream_upload_and_readback(server,tmp_path):
    url,calls=server; client=ImmichClient(url+'/api/','credential')
    assert client.identify()['user_id']=='owner'
    path=tmp_path/'file.mp4';path.write_bytes(b'media-content')
    assert client.upload(path,'2026-10-07T00:00:00Z','abc')['id']=='new'
    assert b'media-content' in calls[-1][3]
    assert calls[-1][2]['x-api-key']=='credential'
    assert client.find_checksum('abc')['id']=='existing'
    sink=io.BytesIO()
    assert client.download('new',sink)==hashlib.sha256(b'original').hexdigest()
    assert sink.getvalue()==b'original'

def test_search_copy_and_soft_delete(server):
    url,calls=server;client=ImmichClient(url,'credential')
    client.search({'createdAt':{'gt':'time'}},'cursor')
    assert json.loads(calls[-1][3])['cursor']=='cursor'
    assert json.loads(calls[-1][3])['orderBy']['field']=='fileCreatedAt'
    client.copy('old','new',{'albums':True,'sidecar':False})
    assert json.loads(calls[-1][3])['sidecar'] is False
    client.trash('old')
    assert json.loads(calls[-1][3])=={'ids':['old'],'force':False}
    with pytest.raises(ImmichError) as error: client.asset('bad')
    assert error.value.status==401
    assert 'secret' not in str(error.value)
