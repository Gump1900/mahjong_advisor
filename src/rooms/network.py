"""Shared authoritative rooms for Web and WXML clients; no client-driven bot steps.

RoomService owns room lifecycle/referees. This coordinator owns authentication,
fixed response windows, frozen bot observations, durable sessions and pacing.
"""
import copy
import hashlib
import fcntl
import json
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .room import RoomError, RoomState, Seat
from .service import RoomService
from ..players.base import Choice
from ..players.heuristic import HeuristicPlayer
from ..simulation.observation import observe
from ..simulation.replay import record, replay, save


class NetworkError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class SharedRooms:
    def __init__(self, path='runs/shared-rooms/state.json', *, bot='ev', autostart=True, pace=.65, table_factory=None, exclusive=False):
        self.path = Path(path) if path else None
        self.file_lock = None
        if self.path and exclusive:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.file_lock = open(self.path.with_suffix('.lock'),'a')
            os.chmod(self.path.with_suffix('.lock'),0o600)
            try:
                fcntl.flock(self.file_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                self.file_lock.close()
                raise RuntimeError('此共享房间存档已有服务占用；网页和小程序应连接同一个服务')
        self.bot = bot
        self.pace = pace
        self.lock = threading.RLock()
        self.service = RoomService(table_factory=table_factory)
        self.codes, self.members, self.entries, self.seen = {}, {}, {}, {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='room-bot')
        self.stopped = threading.Event()
        self.thread = None
        if self.path and self.path.exists():
            self._restore(json.loads(self.path.read_text()))
        if autostart:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _entry(self, table=None):
        return dict(table=table, window=None, observations={}, submitted={}, inflight=set(),
                    bots={}, error=None, due=time.monotonic()+self.pace, requests={})

    def _identity(self, token):
        try:
            return self.service.registry.resolve(token)
        except (KeyError, TypeError):
            raise NetworkError('访客凭证已失效，请重新进入房间', 401)

    def _room(self, token):
        visitor = self._identity(token)['id']
        if visitor not in self.members:
            raise NetworkError('你当前没有加入房间', 404)
        room_id = self.members[visitor]
        return visitor, self.service.room(room_id), self.entries[room_id]

    def identity(self, nickname):
        if not isinstance(nickname, str) or not 1 <= len(nickname.strip()) <= 12:
            raise NetworkError('昵称须为1至12个字', 400)
        with self.lock:
            if len(self.service.registry._visitors) >= 512:
                raise NetworkError('开发服务访客已满，请联系房主', 503)
            _, token = self.service.registry.create(nickname.strip())
            self._persist()
            return {'token': token}

    def profile(self, token):
        with self.lock:
            user = self._identity(token)
            return {'nickname': user['nickname'], 'joined': user['id'] in self.members}

    def create(self, token):
        with self.lock:
            user = self._identity(token)
            if user['id'] not in self.members:
                if len(self.entries) >= 32:
                    raise NetworkError('开发服务房间已满', 503)
                room = self.service.create_room(user['id'], user['nickname'])
                code = str(secrets.randbelow(900000)+100000)
                while code in self.codes:
                    code = str(secrets.randbelow(900000)+100000)
                self.codes[code] = room.room_id
                self.members[user['id']] = room.room_id
                self.entries[room.room_id] = self._entry()
                self._persist()
            return self.view(token)

    def join(self, token, code):
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise NetworkError('请输入6位房间号', 400)
        with self.lock:
            user = self._identity(token)
            target = self.codes.get(code)
            if not target:
                raise NetworkError('房间不存在或已关闭', 404)
            old = self.members.get(user['id'])
            if old and old != target:
                raise NetworkError('请先离开当前房间，再加入另一桌')
            room = self.service.room(target)
            try:
                room.join(user['id'], user['nickname'])
            except RoomError as exc:
                raise NetworkError(str(exc))
            self.members[user['id']] = target
            self._persist()
            return self.view(token)

    def _window(self, entry):
        table = entry['table']
        if table is None or table.stage == 'ended':
            return
        version = f'{table.game_id}:{table._token()}'
        if entry['window'] == version:
            return
        entry.update(window=version, observations={s:observe(table, s) for s in table.waiting_seats()},
                     submitted={}, inflight=set(), due=time.monotonic()+self.pace, error=None)
        for seat, obs in entry['observations'].items():
            if len(obs['legal_actions']) == 1 and obs['legal_actions'][0]['kind'] == 'pass':
                entry['submitted'][seat] = Choice(obs['legal_actions'][0]['id'], 'forced')

    def _game(self, room, entry, seat):
        table = entry['table']
        if table is None:
            return None
        self._window(entry)
        data = observe(table, seat)
        waiting = seat in entry['observations'] and seat not in entry['submitted'] and table.stage != 'ended'
        if not waiting:
            data['legal_actions'] = []
        data.update(version=entry['window'] if table.stage != 'ended' else f'{table.game_id}:ended',
                    awaiting_human=waiting, can_advance=False, shared=True,
                    bot_thinking=bool(entry['inflight']), bot_error=entry['error'])
        for player, seated in zip(data['players'], room.seats):
            player['nickname'] = seated.nickname
        if table.stage == 'ended':
            data['revealed_hands'] = [[str(t) for t in s.hand] for s in table.seats]
        return data

    def view(self, token):
        with self.lock:
            visitor, room, entry = self._room(token)
            self.seen[visitor] = time.time()  # Presence only; GET never advances the referee.
            seat = room.seat_of(visitor)
            phase = 'playing' if room.state is RoomState.PLAYING else 'waiting'
            code = next(c for c, rid in self.codes.items() if rid == room.room_id)
            seats = [dict(index=i, kind=s.kind, nickname=s.nickname, ready=s.ready, me=s.visitor==visitor,
                          host=s.visitor==room.host_visitor,
                          online=s.kind=='bot' or (s.visitor is not None and time.time()-self.seen.get(s.visitor,0)<15))
                     for i, s in enumerate(room.seats)]
            host = visitor == room.host_visitor
            return {'room': {'code':code, 'phase':phase, 'seat':seat, 'host':host, 'seats':seats,
                             'canStart':host and phase=='waiting' and all(s.kind!='empty' and s.ready for s in room.seats),
                             'lastOutcome':room.last_game.get('outcome') if room.last_game else None,
                             'notice':'有玩家离开，上局已中止；重新准备后可开局' if room.last_game and room.last_game.get('outcome')=='aborted' else ''},
                    'game':self._game(room, entry, seat)}

    def _dedupe(self, entry, visitor, request_id, operation, body):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 120:
            raise NetworkError('请求缺少有效request_id', 400)
        key = visitor+':'+request_id
        digest = hashlib.sha256(json.dumps([operation,body],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        previous = entry['requests'].get(key)
        if previous and previous != digest:
            raise NetworkError('请求编号已被另一项操作使用', 400)
        return key, digest, previous is not None

    def command(self, token, operation, body):
        with self.lock:
            visitor, room, entry = self._room(token)
            clean = {k:v for k,v in body.items() if k!='request_id'}
            key, digest, duplicate = self._dedupe(entry, visitor, body.get('request_id'), operation, clean)
            if duplicate:
                return self.view(token)
            host = room.host_visitor == visitor
            seat = room.seat_of(visitor)
            table = entry['table']
            try:
                if operation == 'bots':
                    if not host:
                        raise NetworkError('只有房主可以补齐机器人', 403)
                    room.fill_bots()
                elif operation == 'ready':
                    if room.state is not RoomState.WAITING or type(body.get('ready')) is not bool:
                        raise NetworkError('当前不能修改准备状态')
                    room.set_ready(visitor, body['ready'])
                elif operation == 'start':
                    if not host:
                        raise NetworkError('只有房主可以开局', 403)
                    if room.state is not RoomState.PLAYING:
                        self._archive(entry['table'])
                        self.service.start_hand(room.room_id)
                        entry['table'] = self.service.active_table(room.room_id)
                        room.active_game['game_id'] = entry['table'].game_id
                        entry.update(window=None, error=None, bots={})
                        self._window(entry)
                elif operation in ('action','flowers'):
                    if room.state is not RoomState.PLAYING or not table:
                        raise NetworkError('当前没有进行中的对局')
                    self._window(entry)
                    if body.get('version') != entry['window']:
                        raise NetworkError('局面已更新，请重新选择；旧动作没有执行')
                    if seat not in entry['observations'] or seat in entry['submitted']:
                        raise NetworkError('当前不等待你的动作')
                    if operation == 'flowers':
                        # Batch exchange is only possible during one's turn.
                        table.exchange_flowers(seat, body.get('tiles'), controller='human:room:flowers')
                        entry['window'] = None
                        self._window(entry)
                    else:
                        action = next((a for a in entry['observations'][seat]['legal_actions'] if a['id']==body.get('action_id')), None)
                        if not action:
                            raise NetworkError('不是你当前座位的合法动作', 403)
                        entry['submitted'][seat] = Choice(action['id'],'human:room')
                        self._commit(room,entry, immediate=True, persist=False)
                elif operation == 'retry':
                    if not entry['error']:
                        raise NetworkError('当前没有需要重试的机器人任务')
                    entry['error'] = None
                else:
                    raise NetworkError('未知房间操作', 404)
            except RoomError as exc:
                raise NetworkError(str(exc))
            entry['requests'][key] = digest
            while len(entry['requests']) > 512:
                del entry['requests'][next(iter(entry['requests']))]
            self._persist()
            return self.view(token)

    def leave(self, token):
        with self.lock:
            if self._identity(token)['id'] not in self.members:
                return {'left':True}
            visitor, room, entry = self._room(token)
            self._archive(entry['table'])
            if room.state is RoomState.PLAYING:
                room.abort('玩家主动离桌')
            index = room.seat_of(visitor)
            room.seats[index] = Seat()
            room._connections.pop(visitor,None)
            self.members.pop(visitor,None)
            entry.update(table=None,window=None,submitted={},inflight=set())
            humans = [s for s in room.seats if s.kind=='human']
            if humans:
                if visitor == room.host_visitor:
                    room.host_visitor = humans[0].visitor
            else:
                self.codes = {c:r for c,r in self.codes.items() if r!=room.room_id}
                self.entries.pop(room.room_id)
                self.service._rooms.pop(room.room_id)
                self.service._tables.pop(room.room_id,None)
            self._persist()
            return {'left':True}

    def _commit(self, room, entry, immediate=False, persist=True):
        table = entry['table']
        if not table or table.stage=='ended' or not entry['observations']:
            return
        if not set(entry['observations']).issubset(entry['submitted']):
            return
        if not immediate and time.monotonic()<entry['due']:
            return
        trial = copy.deepcopy(table)
        for seat in sorted(entry['observations']):
            choice = entry['submitted'][seat]
            trial.apply(seat,choice.action_id,controller=choice.controller,reason=choice.reason)
        entry['table'] = trial
        self.service._tables[room.room_id] = trial
        entry['window'] = None
        if trial.stage=='ended':
            room.hand_finished(trial.result['method'])
            entry.update(observations={},submitted={},inflight=set())
        else:
            self._window(entry)
        if persist:
            self._persist()

    def _select(self, rid, window, seat, obs, bot):
        try:
            choice, error = bot.choose(obs), None
            if choice.action_id not in {a['id'] for a in obs['legal_actions']}:
                raise ValueError('机器人没有返回合法动作')
        except Exception:
            choice, error = None, '机器人决策未完成，可重试；牌局保持当前状态'
        with self.lock:
            entry = self.entries.get(rid)
            if not entry or entry['window']!=window:
                return
            entry['inflight'].discard(seat)
            if error:
                entry['error']=error
            else:
                entry['submitted'][seat]=choice
            self._persist()

    def tick(self):
        with self.lock:
            for rid, entry in list(self.entries.items()):
                room = self.service.room(rid)
                if room.state is not RoomState.PLAYING:
                    continue
                self._window(entry)
                if entry['error']:
                    continue
                self._commit(room,entry)
                if room.state is not RoomState.PLAYING:
                    continue
                for seat, obs in entry['observations'].items():
                    if room.seats[seat].kind!='bot' or seat in entry['submitted'] or seat in entry['inflight']:
                        continue
                    if seat not in entry['bots']:
                        if self.bot=='ev':
                            from ..decision.ev_bot import EVBot
                            entry['bots'][seat]=EVBot(room.seats[seat].bot_persona or '均衡',samples=8,seed=seat)
                        else:
                            entry['bots'][seat]=HeuristicPlayer()
                    entry['inflight'].add(seat)
                    self.pool.submit(self._select,rid,entry['window'],seat,copy.deepcopy(obs),entry['bots'][seat])

    def _run(self):
        while not self.stopped.wait(.15):
            self.tick()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=10)
        self.pool.shutdown(wait=True)
        with self.lock:
            self._persist()
        if self.file_lock:
            self.file_lock.close()
            self.file_lock=None

    def _archive(self, table):
        if self.path and table:
            target = self.path.parent/'archives'/f'{table.game_id}-{table.revision}.json'
            if not target.exists():
                save(table,target)

    def _persist(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        data={'format':1, 'service':self.service.to_dict(), 'codes':self.codes, 'members':self.members,
              'entries':{rid:{'replay':record(e['table']) if e['table'] else None,
                              'submitted':{str(s):{'id':c.action_id,'controller':c.controller,'reason':c.reason} for s,c in e['submitted'].items()},
                              'requests':e['requests']} for rid,e in self.entries.items()}}
        temp = self.path.with_suffix('.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,self.path)
        os.chmod(self.path,0o600)

    def _restore(self, data):
        if data.get('format')!=1:
            raise ValueError('不支持的共享房间存档版本')
        self.service=RoomService.from_dict(data['service'])
        self.codes,self.members=data['codes'],data['members']
        for rid,item in data['entries'].items():
            entry=self._entry(replay(item['replay']) if item['replay'] else None)
            self.entries[rid]=entry
            if entry['table']:
                self.service._tables[rid]=entry['table']
                self._window(entry)
                entry['submitted'].update({int(s):Choice(c['id'],c['controller'],c['reason']) for s,c in item['submitted'].items()})
            entry['requests']=item['requests']
