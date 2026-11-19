"""EV 机器人牌桌启动器：复用桌面测试桌（simulation.web），三个座位换成 EVBot。

不修改 simulation/ 任何代码，只做注入式启动：
  python3 -I scripts/ev_table.py [--port 8766] [--seed S] [--resume 牌谱.json]

座位：0=你（人） 1=下家·均衡 2=对家·稳 3=上家·凶；LLM 教练关闭，零 API 费用。
"""
import argparse
import json
import random
import sys
import os
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.simulation.engine import Table                       # noqa: E402
from src.simulation.replay import replay                     # noqa: E402
from src.simulation.web import (                             # noqa: E402
    DesktopHTTPServer, DesktopTable, make_handler,
)
from src.decision.ev_bot import EVBot                        # noqa: E402
from src.decision.ev_coach import EVCoach                     # noqa: E402
from src.webapp.table_ui_patch import (                      # noqa: E402
    make_patched_handler, wrap_desktop,
)

BOT_SETUP = {1: "均衡", 2: "稳", 3: "凶"}


def main():
    parser = argparse.ArgumentParser(description="EV机器人桌面牌桌（注入式，无LLM费用）")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--human-seat", type=int, choices=range(4), default=0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("runs/ev-table"))
    args = parser.parse_args()

    bots = {seat: EVBot(name, samples=32, seed=seat)
            for seat, name in BOT_SETUP.items() if seat != args.human_seat}
    if args.resume:
        table = replay(json.loads(args.resume.read_text(encoding="utf-8")))
    else:
        table = Table(args.seed if args.seed is not None
                      else random.SystemRandom().randrange(2 ** 53), args.human_seat)
    desktop = DesktopTable(table, args.human_seat, str(args.output_dir),
                           paced=True, bots=bots, background=True,
                           auto_coach=False)
    # 注入 EV 常驻军师：替换 LLM 教练插槽（免费），并解除每局调用预算
    desktop.coach = EVCoach()
    desktop.coach_auto = True
    desktop.coach_suspended = False
    _original_auto = desktop._maybe_auto_coach
    def _free_auto_coach():
        desktop.coach_calls = 0          # EV 军师零费用，不吃预算计数
        return _original_auto()
    desktop._maybe_auto_coach = _free_auto_coach
    # UI 注入（2026-11-19 需求）：副露"被拿的那张"记号 + 左侧常驻听牌面板
    wrap_desktop(desktop)
    server = DesktopHTTPServer(("127.0.0.1", args.port),
                               make_patched_handler(make_handler(desktop)))
    print(f"EV机器人牌桌：http://127.0.0.1:{server.server_port}/ "
          f"（座位{args.human_seat}=你；"
          + "；".join(f"座位{s}={n}" for s, n in BOT_SETUP.items() if s != args.human_seat)
          + "；EV常驻军师已注入）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print(f"私有续局牌谱：{desktop.checkpoint()}", flush=True)
        server.server_close()


if __name__ == "__main__":
    main()
