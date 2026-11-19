import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from src.mobile.server import Sessions,make_handler
from src.rooms.network import SharedRooms
from src.simulation.web import DesktopHTTPServer


def test_cross_client_http_identity_and_action_boundary(tmp_path):
    rooms=SharedRooms(tmp_path/'rooms.json',bot='heuristic',autostart=False,pace=0)
    server=DesktopHTTPServer(('127.0.0.1',0),make_handler(Sessions(str(tmp_path)),shared_rooms=rooms))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    sequence=iter(range(100))
    def request(path,body=None,token=''):
        if body is not None:body={**body,'request_id':str(next(sequence))}
        req=Request(f'http://127.0.0.1:{server.server_port}'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Session':token})
        try:
            with urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())
        except HTTPError as e:return e.code,json.loads(e.read())
    try:
        assert request('/api/rooms/state')[0]==401
        assert request('/api/rooms/identity',{'nickname':''})[0]==400
        a=request('/api/rooms/identity',{'nickname':'Web'})[1]['token']
        b=request('/api/rooms/identity',{'nickname':'微信'})[1]['token']
        room=request('/api/rooms/create',{},a)[1]['room']
        assert request('/api/rooms/join',{'code':room['code']},b)[1]['room']['seat']==1
        assert request('/api/rooms/bots',{},b)[0]==403
        assert request('/api/rooms/bots',{},a)[0]==200
        for t in (a,b):assert request('/api/rooms/ready',{'ready':True},t)[0]==200
        state=request('/api/rooms/start',{},a)[1]['game']
        assert request('/api/rooms/state',token=b)[1]['game']['version']==state['version']
        action=next(x for x in state['legal_actions'] if x['kind']=='discard')
        assert request('/api/rooms/action',{'version':state['version'],'action_id':action['id'],'seat':0},b)[0] in (403,409)
        assert request('/api/rooms/action',{'version':state['version'],'action_id':action['id']},a)[0]==200
        other=request('/api/rooms/state',token=b)[1]['game']
        assert any(e['kind']=='discard' and e['seat']==0 for e in other['events'])
        assert all('hand' not in player for player in other['players'])
    finally:
        server.shutdown();server.server_close();thread.join();rooms.close()
