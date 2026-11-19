"""Drive a table using isolated players, collecting one full response window."""
from .observation import observe
from ..players.base import Choice, DecisionError


def play(table, players, *, max_decisions=2000, on_step=None):
    if len(players) != 4:
        raise ValueError("必须配置四个玩家")
    while table.stage != "ended":
        if len(table.decisions) >= max_decisions:
            raise DecisionError("到达动作上限，暂停并保留牌局，不伪造黄庄")
        # Freeze every seat's observation BEFORE collecting any decisions.
        observations = [(seat, observe(table, seat)) for seat in table.waiting_seats()]
        choices = []
        for seat, observation in observations:
            actions = observation["legal_actions"]
            if not actions:
                raise DecisionError("裁判没有合法动作，需检查规则，不自动修补局面")
            if len(actions) == 1 and actions[0]["kind"] == "pass":
                choice = Choice(actions[0]["id"], "forced", "唯一合法动作为过，不存在放弃可胡的机会")
            else:
                choice = players[seat].choose(observation)
            if choice.action_id not in {a["id"] for a in actions}:
                raise DecisionError(f"座位{seat}返回非法或过期动作，已暂停")
            choices.append((seat, choice))
        # Do not apply any response if another player failed/timed out.
        for seat, choice in choices:
            if len(table.decisions) >= max_decisions:
                raise DecisionError("到达动作上限，暂停并保留牌局")
            obs = next(o for s, o in observations if s == seat)
            chosen = next(a for a in obs["legal_actions"] if a["id"] == choice.action_id)
            selector = getattr(players[seat], "select_flowers", None)
            flowers = selector(obs) if chosen["kind"] == "flower_kong" and callable(selector) else []
            if len(flowers) > 1:
                if len(table.decisions)+len(flowers) > max_decisions:
                    raise DecisionError("批量换花将超出动作上限，整组未执行，已暂停")
                table.exchange_flowers(seat, flowers, controller=choice.controller+":batch")
            else:
                table.apply(seat, choice.action_id, controller=choice.controller, reason=choice.reason)
            if on_step:
                on_step(table, seat, choice)
    return table.result
