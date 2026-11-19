"""Shared guest rooms and isolated practice; optional paired LAN development access. No WeChat login."""
import argparse
import json
import mimetypes
import random
import threading
import ipaddress
import os
from secrets import compare_digest
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import unquote, urlsplit

from src.mobile.scenarios import create_table
from src.rooms.network import SharedRooms, NetworkError
from src.simulation.observation import observe
from src.simulation.web import DesktopHTTPServer, DesktopTable
from src.players.base import DecisionError
from src.players.heuristic import HeuristicPlayer

ROOT = Path(__file__).resolve().parents[2] / 'clients' / 'miniprogram'


class MobileTable(DesktopTable):
    def view(self):
        with self.lock:
            data = observe(self.table, self.human)
            data.update(version=self.version, bot_error=self.bot_error,
                        bot_thinking=self.thinking,
                        awaiting_human=any(c is None for _, c in self.batch) and self.table.stage != 'ended',
                        can_advance=bool(self.batch) and not any(c is None for _, c in self.batch) and self.table.stage != 'ended')
            if self.table.stage == 'ended':
                data['revealed_hands'] = [[str(t) for t in s.hand] for s in self.table.seats]
            return data


class Sessions:
    def __init__(self, output_dir='runs/mobile', bot='ev'):
        self.tables = {}
        self.lock = threading.RLock()
        self.output_dir, self.bot = output_dir, bot

    def create(self, seed=None, scenario="random"):
        if seed is not None and (type(seed) is not int or not 0 <= seed < 2**53):
            raise ValueError('复现种子须为0至9007199254740991的整数')
        with self.lock:
            # Explicitly reject capacity rather than discard an unfinished table.
            if len(self.tables) >= 16:
                raise ValueError('本地测试桌已达16桌，请先结束旧桌或重启服务')
            if self.bot == 'ev':
                from src.decision.ev_bot import EVBot
                bots = {s: EVBot(n, samples=8, seed=s) for s, n in ((1, '均衡'), (2, '稳'), (3, '凶'))}
            else:
                bots = {s: HeuristicPlayer() for s in (1, 2, 3)}
            d = MobileTable(create_table(seed if seed is not None else random.SystemRandom().randrange(2**53), scenario),
                            bots=bots, output_dir=self.output_dir, paced=True, background=True)
            token = token_urlsafe(24)
            self.tables[token] = d
            return {'session': token, 'state': d.view()}

    def get(self, token):
        with self.lock:
            if not isinstance(token, str) or token not in self.tables:
                raise KeyError('测试桌不存在或服务已重启，请回到入口重新开桌')
            return self.tables[token]


def make_handler(sessions, *, allowed_hosts=(), dev_key=None, shared_rooms=None):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, content_type='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            hosts = ('localhost', '127.0.0.1', *allowed_hosts)
            return self.headers.get('Host') in {f'{host}:{self.server.server_port}' for host in hosts}

        def paired(self):
            return not dev_key or compare_digest(self.headers.get('X-Dev-Key', '').encode(), dev_key.encode())


        def do_GET(self):
            if not self.local():
                return self.send(403, {'error': '访问地址不在开发服务允许列表中'})
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/') and not self.paired():
                return self.send(401, {'error': '开发配对码不正确，请检查连接设置'})
            if path == '/api/health':
                return self.send(200, {'protocol': 'taihu-mobile-1', 'status': 'ok'})
            if shared_rooms and path == '/api/rooms/state':
                try:
                    return self.send(200, shared_rooms.view(self.headers.get('X-Session')))
                except NetworkError as exc:
                    return self.send(exc.status, {'error': str(exc)})
            if shared_rooms and path == '/api/rooms/profile':
                try:
                    return self.send(200, shared_rooms.profile(self.headers.get('X-Session')))
                except NetworkError as exc:
                    return self.send(exc.status, {'error': str(exc)})
            if path == '/api/state':
                try:
                    return self.send(200, sessions.get(self.headers.get('X-Session')).view())
                except KeyError as exc:
                    return self.send(404, {'error': exc.args[0]})
            target = (ROOT / ('simulator/index.html' if path == '/' else path.lstrip('/'))).resolve()
            allowed = any(target.is_relative_to(ROOT / p) for p in ('simulator', 'shared', 'assets'))
            if not allowed or not target.is_file():
                return self.send(404, {'error': '资源不存在'})
            return self.send(200, target.read_bytes(), 'text/css; charset=utf-8' if target.suffix == '.wxss' else mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.local() or (origin and origin != 'http://' + self.headers.get('Host', '')):
                return self.send(403, {'error': '拒绝跨站操作'})
            if not self.paired():
                return self.send(401, {'error': '开发配对码不正确，请检查连接设置'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.send(415, {'error': '请求须为JSON'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 10000:
                    raise ValueError('请求过大或为空')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('请求须为JSON对象')
                path = urlsplit(self.path).path
                if shared_rooms and path.startswith('/api/rooms/'):
                    operation = path.rsplit('/',1)[-1]
                    token = self.headers.get('X-Session')
                    if operation == 'identity':
                        result = shared_rooms.identity(body.get('nickname'))
                    elif operation == 'create':
                        result = shared_rooms.create(token)
                    elif operation == 'join':
                        result = shared_rooms.join(token,body.get('code'))
                    elif operation == 'leave':
                        result = shared_rooms.leave(token)
                    else:
                        result = shared_rooms.command(token,operation,body)
                    return self.send(200,result)
                if path == '/api/session':
                    return self.send(200, sessions.create(body.get('seed'), body.get('scenario', 'random')))
                token = self.headers.get('X-Session')
                d = sessions.get(token)
                version = body.get('version')
                if path == '/api/action':
                    result = d.action(version, body.get('action_id'))
                elif path == '/api/flowers':
                    result = d.exchange_flowers(version, body.get('tiles'))
                elif path == '/api/step':
                    result = d.step(version)
                elif path == '/api/retry':
                    result = d.retry_bots(version)
                elif path == '/api/new':
                    result = d.new_game(version, body.get('seed'))
                elif path == '/api/close':
                    with sessions.lock, d.lock:
                        d._require_version(version)
                        d.checkpoint()
                        del sessions.tables[token]
                    return self.send(200, {'closed': True})
                else:
                    return self.send(404, {'error': '接口不存在'})
                result.pop('frames', None)  # Live state only; no web animation dependency.
                return self.send(200, result)
            except NetworkError as exc:
                return self.send(exc.status, {'error': str(exc)})
            except KeyError as exc:
                return self.send(404, {'error': exc.args[0]})
            except (ValueError, TypeError, DecisionError) as exc:
                return self.send(400, {'error': str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description='原生小程序与手机模拟器的本地对局服务')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--bot', choices=('ev', 'heuristic'), default='ev')
    parser.add_argument('--host', default='127.0.0.1', choices=('127.0.0.1', '0.0.0.0'))
    parser.add_argument('--allow-host', action='append', default=[], help='允许访问的电脑局域网IPv4地址')
    parser.add_argument('--rooms-state', type=Path, default=Path('runs/shared-rooms/state.json'))
    parser.add_argument('--pair-file', type=Path, default=Path('var/mobile-pairing.json'))
    args = parser.parse_args()
    dev_key = None
    if args.host == '0.0.0.0':
        if not args.allow_host:
            parser.error('局域网模式需要 --allow-host 电脑的局域网IPv4地址')
        for host in args.allow_host:
            try:
                address = ipaddress.ip_address(host)
                if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
                    raise ValueError()
            except ValueError:
                parser.error('--allow-host 只接受局域网IPv4地址')
        args.pair_file.parent.mkdir(parents=True, exist_ok=True)
        if args.pair_file.exists():
            dev_key = json.loads(args.pair_file.read_text())['devKey']
            if not isinstance(dev_key, str) or len(dev_key) < 24:
                parser.error('本地配对文件无效')
        else:
            dev_key = token_urlsafe(24)
        body = {'baseURL': f'http://{args.allow_host[0]}:{args.port}', 'devKey': dev_key}
        fd = os.open(args.pair_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as pairing:
            json.dump(body, pairing, ensure_ascii=False, indent=2)
        os.chmod(args.pair_file, 0o600)
        print(f'局域网配对配置：{args.pair_file.resolve()}（仅开发调试）', flush=True)
    shared = SharedRooms(path=args.rooms_state, bot=args.bot, exclusive=True)
    try:
        server = DesktopHTTPServer((args.host, args.port), make_handler(Sessions(bot=args.bot), allowed_hosts=args.allow_host, dev_key=dev_key, shared_rooms=shared))
    except BaseException:
        shared.close()
        raise
    print(f'手机试打模拟器：http://127.0.0.1:{server.server_port}/ （跨端房间＋单人陪练，无军师、无API费用）', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shared.close()


if __name__ == '__main__':
    main()
