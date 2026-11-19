"""Mobile transport reuses referee validation; testing endpoints cannot leak truth."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.mobile.server import Sessions, make_handler
from src.simulation.web import DesktopHTTPServer
from src.players.heuristic import HeuristicPlayer


@pytest.fixture
def service(tmp_path):
    sessions = Sessions(str(tmp_path), bot='heuristic')
    server = DesktopHTTPServer(('127.0.0.1', 0), make_handler(sessions))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, body=None, token='', **headers):
        req = Request(f'http://127.0.0.1:{server.server_port}'+path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type':'application/json','X-Session':token,**headers})
        try:
            with urlopen(req, timeout=10) as response:
                content = response.read()
                return response.status, json.loads(content) if 'json' in response.headers['Content-Type'] else content
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())
    yield sessions, request
    server.shutdown()
    server.server_close()
    thread.join()


def test_mobile_sessions_privacy_versions_and_origin(service):
    sessions, request = service
    _, a = request('/api/session', {'seed':42})
    _, b = request('/api/session', {'seed':43})
    assert a['session'] != b['session']
    assert 'seed' not in a['state'] and 'wall' not in a['state']
    assert all('hand' not in p for p in a['state']['players'])
    assert 'coach' not in json.dumps(a['state'])
    d = sessions.get(a['session'])
    for _ in range(1000):
        if not d.thinking:
            break
        threading.Event().wait(.001)
    state = d.view()
    action = state['legal_actions'][0]
    before_b = sessions.get(b['session']).version
    status, _ = request('/api/action', {'version':'stale','action_id':action['id']}, a['session'])
    assert status == 400 and d.version == state['version']
    status, _ = request('/api/action', {'version':state['version'],'action_id':action['id']}, a['session'], Origin='https://unrelated.example')
    assert status == 403 and d.version == state['version']
    status, after = request('/api/action', {'version':state['version'],'action_id':action['id']}, a['session'])
    assert status == 200 and after['version'] != state['version']
    assert sessions.get(b['session']).version == before_b
    assert request('/api/state', token='missing')[0] == 404
    assert request('/../app.js')[0] == 404
    assert request('/shared/mobile.wxss')[0] == 200


def test_mobile_complete_game_and_resume(service):
    sessions, request = service
    _, created = request('/api/session', {'seed':42})
    token = created['session']
    d = sessions.get(token)
    bot = HeuristicPlayer()
    for _ in range(5000):
        state = d.view()
        if state['stage'] == 'ended':
            break
        if state['bot_thinking']:
            threading.Event().wait(.002)
            continue
        if state['awaiting_human']:
            status, state = request('/api/action', {'version':state['version'],'action_id':bot.choose(state).action_id}, token)
        else:
            status, state = request('/api/step', {'version':state['version']}, token)
        assert status == 200
    assert state['stage'] == 'ended' and sum(state['result']['net']) == 0
    assert request('/api/state', token=token)[1]['version'] == state['version']
    assert request('/api/new', {'version':state['version'],'seed':43}, token)[0] == 200
    state = d.view()
    assert request('/api/close', {'version':state['version']}, token)[0] == 200
    assert request('/api/state', token=token)[0] == 404

@pytest.mark.parametrize('scenario,kind', [('chi','chi'),('peng','peng'),('ming','ming_gang'),('an','an_gang'),('flowers','flower_kong'),('win','win')])
def test_mobile_cases_use_legal_physical_deck(scenario, kind):
    from src.mobile.scenarios import create_table
    from src.simulation.replay import record, replay
    from src.simulation.observation import observe
    table = create_table(42, scenario)
    table.assert_consistent()
    state = observe(table, 0)
    action = next(a for a in table.legal_actions(0) if a.kind == kind)
    if state['stage'] == 'responses':
        # Collect responses without leaking other seats' choices into the client.
        for seat in list(table.waiting_seats()):
            chosen = action if seat == 0 else next(a for a in table.legal_actions(seat) if a.kind == 'pass')
            table.apply(seat, chosen.id)
    else:
        table.apply(0, action.id)
    table.assert_consistent()
    assert replay(record(table)).state_hash() == table.state_hash()

def test_mobile_development_health_and_pairing(tmp_path):
    sessions = Sessions(str(tmp_path), bot='heuristic')
    server = DesktopHTTPServer(('127.0.0.1', 0), make_handler(sessions, allowed_hosts=('192.168.1.4',), dev_key='development-pairing-key'))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(key='', host=None, path='/api/health', body=None):
        headers={'X-Dev-Key':key,'Content-Type':'application/json'}
        if host: headers['Host']=f'{host}:{server.server_port}'
        req=Request(f'http://127.0.0.1:{server.server_port}{path}',headers=headers,data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req,timeout=5) as response: return response.status,json.loads(response.read())
        except HTTPError as exc: return exc.code,json.loads(exc.read())
    try:
        assert request()[0] == 401
        assert request('wrong', path='/api/session',body={})[0] == 401
        assert request('development-pairing-key','192.168.1.4')[1]['protocol'] == 'taihu-mobile-1'
        assert request('development-pairing-key','192.168.1.99')[0] == 403
        assert request('development-pairing-key')[1] == {'protocol':'taihu-mobile-1','status':'ok'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
