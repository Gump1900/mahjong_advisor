"""人机对局驱动器：你(座位0) + 三个EV机器人，逐步在终端/对话里对打。

用法：
  python3 -I scripts/play_vs_bots.py new [种子]    # 开新局并推进到你的首个决策
  python3 -I scripts/play_vs_bots.py               # 查看当前局面、EV建议、可选动作
  python3 -I scripts/play_vs_bots.py move <动作id>  # 执行你的选择，机器人自动推进到下一决策

状态存 runs/ev-play/current.json（裁判全知快照，含复盘真值）。
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.simulation.engine import Table                      # noqa: E402
from src.simulation.observation import observe               # noqa: E402
from src.simulation.replay import record, replay            # noqa: E402
from src.decision.ev import opponent_panel, rank_candidates  # noqa: E402
from src.decision.ev_bot import EVBot, build_state_from_observation  # noqa: E402
from src.decision.receipts import load_receipts, save_receipt  # noqa: E402
from src.decision.replay_review import dual_review           # noqa: E402
from src.players.base import LABELS                          # noqa: E402

SAVE = "runs/ev-play/current.json"
HUMAN = 0
BOT_SETUP = {1: "均衡", 2: "稳", 3: "凶"}       # 座位1=下家, 2=对家, 3=上家
SEAT_ZH = {0: "你", 1: "下家(均衡)", 2: "对家(稳)", 3: "上家(凶)"}


def load_table():
    if not os.path.exists(SAVE):
        return None
    return replay(json.load(open(SAVE, encoding="utf-8")))


def store(table):
    os.makedirs(os.path.dirname(SAVE), exist_ok=True)
    with open(SAVE, "w", encoding="utf-8") as fh:
        json.dump(record(table), fh, ensure_ascii=False, indent=2)


def make_bots():
    return {seat: EVBot(name, samples=64, seed=seat)
            for seat, name in BOT_SETUP.items()}


def forced_pass(actions):
    return len(actions) == 1 and actions[0]["kind"] == "pass"


def apply_choice(table, seat, choice, observation):
    chosen = next(a for a in observation["legal_actions"]
                  if a["id"] == choice.action_id)
    if chosen["kind"] == "flower_kong":
        selector = getattr(choice, "select_flowers", None)
        flowers = selector(observation) if selector else None
        if flowers is None:
            player = table.seats[seat]
            from src.core.tiles import parse_tile as _pt
            flowers = [t for t in player.hand if str(t) == chosen["tiles"][0]]
        if len(flowers) > 1:
            table.exchange_flowers(seat, flowers, controller=choice.controller)
            return
    table.apply(seat, choice.action_id, controller=choice.controller,
                reason=choice.reason)


def ev_advice(observation):
    state = build_state_from_observation(observation)
    ranked = rank_candidates(state, samples=64, seed=0)
    panel = opponent_panel(state, samples=64, seed=0)
    return ranked, panel


def print_decision(observation):
    self_info = observation["self"]
    hand = " ".join(self_info["hand"])
    print(f"=== 你的回合（{observation['stage']}）｜牌墙 {observation['wall_count']} 张 ===")
    print(f"手牌：{hand}")
    if self_info.get("structural_shanten") is not None:
        print(f"向听：{self_info['structural_shanten']}｜过胡未过圈：{self_info['ron_blocked']}"
              f"｜互锁对象：{self_info['locked_with'] or '无'}")
    actions = observation["legal_actions"]
    unexchanged = self_info.get("held_flower_count", 0)
    flower_actions = [a for a in actions if a["kind"] == "flower_kong"]
    discard_like = [a for a in actions if a["kind"] == "discard"]
    if unexchanged and flower_actions:
        print(f"\n【建议】手牌有 {unexchanged} 张未换花（花占位，EV 层暂只支持换花后的手牌）。")
        print("  先换花（听牌后留花搏杠开是进阶打法；现在换=立即补牌+花分落袋）")
    if discard_like and not unexchanged:
        try:
            ranked, panel = ev_advice(observation)
        except ValueError as exc:
            print(f"\n【EV 建议】不可用：{exc}")
            ranked = None
        if ranked:
            print("\n【EV 建议】(先验采样N=64，本巡口径：EV=自摸概率×收益−点炮概率×损失)")
            for cand in ranked[:4]:
                print(f"  打{cand.tile}: EV={cand.ev:+.3f}｜自摸{cand.p_win_next:.1%}×{cand.v_win:.0f}"
                      f" − 点炮{cand.p_point:.1%}×{cand.v_deal:.0f}｜进张{cand.exp_neff_1ply:.0f}张")
            for note in ranked[0].labels:
                print(f"  标签: {note}")
            print("对手听牌先验：上家 {0:.0%}｜对家 {1:.0%}｜下家 {2:.0%}".format(
                panel["left"]["tenpai_prior"], panel["opposite"]["tenpai_prior"],
                panel["right"]["tenpai_prior"]))
    print("\n【可选动作】")
    for action in actions:
        extra = ""
        if action.get("score_per_payer"):
            extra = f"（每家付 {action['score_per_payer']} 花）"
        print(f"  [{action['id']}] {LABELS.get(action['kind'], action['kind'])} "
              f"{' '.join(action.get('tiles') or [])} {extra}")


def advance(table, *, stop_at_human=True):
    """推进到我的下一个非强制决策或终局。返回我的 observation 或 None。"""
    bots = make_bots()
    while table.stage != "ended":
        waiting = table.waiting_seats()
        frozen = [(seat, observe(table, seat)) for seat in waiting]
        human_seat = next((s for s, o in frozen
                           if s == HUMAN and not forced_pass(o["legal_actions"])), None)
        if human_seat is not None and stop_at_human:
            store(table)
            return next(o for s, o in frozen if s == HUMAN)
        for seat, obs in frozen:
            actions = obs["legal_actions"]
            if forced_pass(actions):
                table.apply(seat, actions[0]["id"], controller="forced")
                continue
            choice = bots[seat].choose(obs)
            apply_choice(table, seat, choice, obs)
            print(f"  {SEAT_ZH[seat]} -> {LABELS.get(actions_kind(actions, choice), '?')}"
                  f" {' '.join(next(a for a in actions if a['id'] == choice.action_id)['tiles'] or [])}")
    store(table)
    return None


def actions_kind(actions, choice):
    return next(a["kind"] for a in actions if a["id"] == choice.action_id)


def print_result(table):
    result = table.result
    print("\n=== 对局结束 ===")
    print(json.dumps(result["net"], ensure_ascii=False) if result else "无结果")
    snap = table.snapshot()
    truth = {}
    for seat_info in snap["seats"]:
        idx = snap["seats"].index(seat_info)
        if idx == HUMAN:
            continue
        name = {1: "right", 2: "opposite", 3: "left"}[idx]
        truth[name] = {"hand": seat_info["hand"], "melds": len(seat_info["melds"])}
    receipts = load_receipts(table.game_id)
    if receipts:
        review = dual_review(receipts, truth)
        print("\n【复盘双通道：先验 vs 摊牌真值】")
        for row in review:
            print(f"  rev{row['revision']} 打{row['tile']}: 先验{row['prior_p']:.2f} "
                  f"真值{row['true_p'] if row['true_p'] is not None else '不全'} "
                  f"偏差{row['delta'] if row['delta'] is not None else '-'}")


def main(argv):
    if argv and argv[0] == "new":
        seed = int(argv[1]) if len(argv) > 1 else random.randrange(10 ** 6)
        table = Table(seed=seed, dealer=HUMAN)
        print(f"新对局 game_id={table.game_id} seed={seed}（你坐庄，座位0；"
              f"下家=均衡 对家=稳 上家=凶）")
        store(table)
    table = load_table()
    if table is None:
        print("还没有对局，先运行: python3 -I scripts/play_vs_bots.py new")
        return 1
    if table.stage == "ended":
        print_result(table)
        return 0
    if argv and argv[0] == "move":
        action_id = argv[1]
        waiting = table.waiting_seats()
        frozen = [(seat, observe(table, seat)) for seat in waiting]
        my_obs = next((o for s, o in frozen if s == HUMAN), None)
        if my_obs is None:
            print("现在不是你的决策点")
            return 1
        legal = {a["id"] for a in my_obs["legal_actions"]}
        if action_id not in legal:
            print(f"动作 {action_id} 不合法。可选：{sorted(legal)}")
            return 1
        # 同批先取我的选择，再补机器人的确定性选择（runner 语义：先冻结观察）
        from src.players.base import Choice
        my_choice = Choice(action_id, "human", "用户选择")
        bots = make_bots()
        for seat, obs in frozen:
            actions = obs["legal_actions"]
            if forced_pass(actions):
                table.apply(seat, actions[0]["id"], controller="forced")
                continue
            if seat == HUMAN:
                if any(a["kind"] == "discard" for a in actions):
                    state = build_state_from_observation(obs)
                    save_receipt(table.game_id, table.revision,
                                 rank_candidates(state, samples=64, seed=0))
                table.apply(seat, action_id, controller="human")
                continue
            choice = bots[seat].choose(obs)
            apply_choice(table, seat, choice, obs)
            print(f"  {SEAT_ZH[seat]} -> {LABELS.get(actions_kind(actions, choice), '?')}"
                  f" {' '.join(next(a for a in actions if a['id'] == choice.action_id)['tiles'] or [])}")
    obs = advance(table)
    if obs is None:
        print_result(table)
    else:
        print_decision(obs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
