"""Desktop terminal player. No private opponents' information is displayed."""
from .base import Choice, LABELS
from .render import tile_face, tile_line
from ..core.tiles import parse_tile, tile_sort_key


class HumanPlayer:
    def __init__(self, input_fn=input, print_fn=print, *, tile_style="unicode"):
        if tile_style not in ("unicode", "text"):
            raise ValueError("牌面样式须为unicode或text")
        self.input, self.print = input_fn, print_fn
        self.tile_style = tile_style

    def choose(self, observation):
        faces = lambda names: tile_line(names, self.tile_style)
        if observation["stage"] == "responses":
            phase = "响应弃牌（还没摸牌，可放弃吃碰胡）"
        else:
            phase = {"initial": "庄家起手选择", "replacement": "补牌后的选择",
                     "normal": "已摸牌，轮到你选择", "claim": "吃碰后直接打牌"}.get(
                         observation["self"].get("draw_source"), "你的回合")
        self.print(f"\n=== {phase}：座位{observation['seat']}，牌墙{observation['wall_count']}张 ===")
        for player in observation["players"]:
            backs = "🀫 🀫 🀫 🀫" if self.tile_style == "unicode" else "未知四张"
            melds = [f"暗杠[{backs}]" if m["hidden"] else f"{m['type']}:{faces(m['tiles'])}"
                     for m in player["melds"]]
            self.print(f"座位{player['seat']}：手牌{player['hand_count']}；"
                       f"牌河 {faces(player['river']) or '无'}；"
                       f"成组 {' / '.join(melds) or '无'}；已换花 {faces(player['flowers']) or '无'}")
        hand = sorted((parse_tile(t) for t in observation["self"]["hand"]), key=tile_sort_key)
        self.print(f"你的手牌（共{len(hand)}张，含留花；以下保留所有重复牌）：")
        for label in ("万", "饼", "条", "字牌", "留花"):
            group = [str(t) for t in hand if (
                "留花" if t.is_flower else t.suit if t.suit in ("万", "饼", "条") else "字牌") == label]
            if group:
                self.print(f"  {label}：{faces(group)}")
        if observation["self"].get("drawn_tile"):
            source = "补牌" if observation["self"].get("draw_source") == "replacement" else "摸牌"
            tile = tile_face(observation['self']['drawn_tile'], self.tile_style, with_name=True)
            self.print(f"【本次{source}】{tile}（已计入上述手牌，未跳过摸牌）")
        if observation["self"]["ron_blocked"]:
            self.print("你已过胡：取得自己的回合前不能接任何炮。")
        if observation["pending"]:
            tile = tile_face(observation['pending']['tile'], self.tile_style, with_name=True)
            self.print(f"座位{observation['pending']['source']}打出 {tile}")
        priorities = {"win": 0, "ron": 0, "discard": 1, "flower_kong": 2,
                      "an_gang": 3, "add_gang": 4, "peng": 5, "ming_gang": 6,
                      "chi": 7, "pass": 8}
        # Sort a display copy only; action IDs and replay order stay unchanged.
        actions = sorted(observation["legal_actions"], key=lambda a: (
            priorities[a["kind"]], tuple(tile_sort_key(parse_tile(t)) for t in a["tiles"])))
        self.print(f"可选动作（共{len(actions)}项，不是手牌张数）：")
        self.print("相同牌只列一个“打”动作，每次只打一张；一次选一个编号，执行后菜单会更新。")
        for i, action in enumerate(actions, 1):
            suffix = f"（每位付款方{action['score_per_payer']}点）" if "score_per_payer" in action else ""
            label = "放弃本次吃碰胡（不是跳过自己的回合）" if action["kind"] == "pass" else LABELS[action["kind"]]
            tiles = " ".join(tile_face(t, self.tile_style, with_name=True) for t in action["tiles"])
            self.print(f" {i:2}. {label} {tiles}{suffix}")
        can_ron = any(a["kind"] == "ron" for a in actions)
        if can_ron:
            self.print("提醒：这张可以接炮；若放弃胡牌，过圈前所有接炮机会都会暂时关闭。")
        while True:
            answer = self.input("选动作编号（q 保存并退出）：").strip()
            if answer.lower() == "q":
                raise KeyboardInterrupt
            if len(answer.split()) > 1:
                self.print("一次只能选一个动作；换牌后编号可能变化，请按新菜单继续选择。")
                continue
            try:
                action = actions[int(answer)-1]
                if not 1 <= int(answer) <= len(actions):
                    raise ValueError
                if action["kind"] == "pass":
                    self.print("已放弃这张弃牌的响应；若无人鸣牌，按座位顺序照常摸牌，不会跳过你的正常回合。")
                    if can_ron:
                        self.print("本次已过胡；正常取得回合或通过吃碰取得回合后，才恢复接炮资格。")
                return Choice(action["id"], "human")
            except (ValueError, IndexError):
                self.print("请输入列表中的编号。")
