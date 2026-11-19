import json
import time

import pytest

from src.rooms.network import SharedRooms, NetworkError
from src.simulation.observation import observe
from src.players.heuristic import HeuristicPlayer


@pytest.fixture
def rooms(tmp_path):
    rooms=SharedRooms(tmp_path/'state.json',bot='heuristic',autostart=False,pace=0)
    yield rooms
    rooms.close()


def person(rooms,name): return rooms.identity(name)['token']
def cmd(rooms,token,kind,**body): return rooms.command(token,kind,{'request_id':str(time.time_ns()),**body})
def humans(rooms,n):
    tokens=[person(rooms,f'玩家{i}') for i in range(n)]
    view=rooms.create(tokens[0])
    for t in tokens[1:]: rooms.join(t,view['room']['code'])
    if n<4: cmd(rooms,tokens[0],'bots')
    for t in tokens: cmd(rooms,t,'ready',ready=True)
    cmd(rooms,tokens[0],'start')
    return tokens


def test_shared_identity_room_permissions_and_privacy(rooms):
    a,b=person(rooms,'网页'),person(rooms,'微信')
    room=rooms.create(a)['room']
    assert rooms.create(a)['room']['code']==room['code']
    v=rooms.join(b,room['code'])
    assert v['room']['seat']==1 and not v['room']['host']
    with pytest.raises(NetworkError,match='房主'): cmd(rooms,b,'bots')
    cmd(rooms,a,'bots')
    with pytest.raises(NetworkError,match='准备'): cmd(rooms,a,'start')
    cmd(rooms,a,'ready',ready=True);cmd(rooms,b,'ready',ready=True)
    va=cmd(rooms,a,'start');vb=rooms.view(b)
    assert va['game']['version']==vb['game']['version']
    assert va['game']['seat']==0 and vb['game']['seat']==1
    assert len(va['game']['self']['hand'])==14 and len(vb['game']['self']['hand'])==13
    assert all('hand' not in p for p in vb['game']['players'])
    text=json.dumps(vb)
    assert all(key not in text for key in ('initial_wall','revealed_hands','"seed"','"visitor"','"token"'))
    with pytest.raises(NetworkError,match='房主'):cmd(rooms,b,'start')
    c=person(rooms,'迟到')
    with pytest.raises(NetworkError,match='开始'):rooms.join(c,room['code'])
    with pytest.raises(NetworkError):rooms.view('bad-token')


def test_same_window_responses_do_not_invalidate_other_humans(tmp_path):
    from collections import Counter
    from src.core.tiles import parse_tile
    from src.simulation.state import full_deck
    from src.simulation.engine import Table
    def fixture(seed,dealer):
        own=[parse_tile(t) for t in '1条 2条 4条 1万 2万 3万 4万 5万 6万 7饼 8饼 南风 南风'.split()]
        fixed={4*i+1:t for i,t in enumerate(own)}
        fixed.update({2:parse_tile('3条'),6:parse_tile('3条'),52:parse_tile('3条')})
        deck=full_deck();remaining=Counter(deck)-Counter(fixed.values());rest=[]
        for t in deck:
            if remaining[t]:rest.append(t);remaining[t]-=1
        rest=iter(rest)
        table=Table(seed,3,wall=[fixed[i] if i in fixed else next(rest) for i in range(144)])
        discard=next(a for a in table.legal_actions(3) if a.kind=='discard' and str(a.tiles[0])=='3条')
        table.apply(3,discard.id)
        return table
    rooms=SharedRooms(tmp_path/'responses.json',bot='heuristic',autostart=False,pace=0,table_factory=fixture)
    try:
        tokens=humans(rooms,4)
        a,b=rooms.view(tokens[0])['game'],rooms.view(tokens[1])['game']
        assert a['stage']=='responses' and a['version']==b['version']
        assert any(x['kind']=='chi' for x in a['legal_actions'])
        assert any(x['kind']=='peng' for x in b['legal_actions'])
        passed=next(x for x in a['legal_actions'] if x['kind']=='pass')
        cmd(rooms,tokens[0],'action',version=a['version'],action_id=passed['id'])
        assert rooms.view(tokens[1])['game']['version']==a['version']
        restored=SharedRooms(rooms.path,bot='heuristic',autostart=False,pace=0)
        try:
            assert not restored.view(tokens[0])['game']['awaiting_human']
            assert restored.view(tokens[1])['game']['awaiting_human']
            peng=next(x for x in b['legal_actions'] if x['kind']=='peng')
            cmd(restored,tokens[1],'action',version=b['version'],action_id=peng['id'])
            assert len(restored.view(tokens[1])['game']['players'][1]['melds'])==1
        finally:restored.close()
    finally:rooms.close()


def test_idempotent_action_and_restore_pending_choices(rooms):
    tokens=humans(rooms,4)
    first=rooms.view(tokens[0])['game']
    action=HeuristicPlayer().choose(first)
    body={'request_id':'fixed-request','version':first['version'],'action_id':action.action_id}
    result=rooms.command(tokens[0],'action',body)
    assert rooms.command(tokens[0],'action',body)['game']['version']==result['game']['version']
    with pytest.raises(NetworkError,match='编号'): rooms.command(tokens[0],'ready',{**body,'ready':True})
    with pytest.raises(NetworkError):cmd(rooms,tokens[1],'action',version=first['version'],action_id=action.action_id)
    restored=SharedRooms(rooms.path,bot='heuristic',autostart=False,pace=0)
    try:
        assert restored.view(tokens[0])['game']['version']==result['game']['version']
        assert restored.view(tokens[1])['room']['code']==result['room']['code']
        assert rooms.path.stat().st_mode & 0o777 == 0o600
    finally:restored.close()


@pytest.mark.parametrize('count',[1,2,3,4])
def test_complete_shared_rounds_and_new_ready_gate(rooms,count):
    tokens=humans(rooms,count)
    bot=HeuristicPlayer()
    for _ in range(4000):
        for token in tokens:
            state=rooms.view(token)['game']
            if state['stage']=='ended':break
            if state['awaiting_human']:
                cmd(rooms,token,'action',version=state['version'],action_id=bot.choose(state).action_id)
        rooms.tick()
        final=rooms.view(tokens[0])
        if final['game']['stage']=='ended':break
        time.sleep(.001)
    assert final['game']['stage']=='ended'
    assert sum(final['game']['result']['net'])==0
    assert all(rooms.view(t)['game']['result']==final['game']['result'] for t in tokens)
    assert final['room']['phase']=='waiting'
    assert not any(s['ready'] for s in final['room']['seats'] if s['kind']=='human')
    with pytest.raises(NetworkError,match='准备'):cmd(rooms,tokens[0],'start')


def test_explicit_leave_aborts_but_disconnect_does_not(rooms):
    a,b=humans(rooms,2)
    before=rooms.view(b)['game']['version']
    assert rooms.view(a)['game']['version']==before
    # A missing client sends no request; there is no silent seat takeover.
    rooms.seen[rooms._identity(a)['id']]=0
    assert not rooms.view(b)['room']['seats'][0]['online']
    assert rooms.view(b)['game']['version']==before
    rooms.leave(a)
    v=rooms.view(b)
    assert v['room']['host'] and v['room']['phase']=='waiting' and v['game'] is None
    assert v['room']['lastOutcome']=='aborted'

def test_shared_state_excludes_second_server_writer(tmp_path):
    a=SharedRooms(tmp_path/'state.json',bot='heuristic',autostart=False,exclusive=True)
    try:
        with pytest.raises(RuntimeError,match='已有服务'):
            SharedRooms(tmp_path/'state.json',bot='heuristic',autostart=False,exclusive=True)
    finally:a.close()
    b=SharedRooms(tmp_path/'state.json',bot='heuristic',autostart=False,exclusive=True)
    b.close()

def test_shared_batch_flower_exchange_is_single_idempotent_command():
    from src.mobile.scenarios import create_table
    rooms=SharedRooms(None,bot='heuristic',autostart=False,pace=0,table_factory=lambda seed,dealer:create_table(42,'flowers'))
    try:
        tokens=humans(rooms,2)
        before=rooms.view(tokens[0])['game']
        body={'request_id':'batch-flowers','version':before['version'],'tiles':['春','中']}
        after=rooms.command(tokens[0],'flowers',body)['game']
        assert after['wall_count']==before['wall_count']-2
        assert len(after['self']['hand'])==len(before['self']['hand'])
        assert after['players'][0]['flowers']==['春','中']
        again=rooms.command(tokens[0],'flowers',body)['game']
        assert again['version']==after['version'] and again['wall_count']==after['wall_count']
        assert rooms.view(tokens[1])['game']['players'][0]['flowers']==['春','中']
    finally:rooms.close()
