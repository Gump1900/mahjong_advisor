"""Uniform human, code and LLM decision interface."""
from dataclasses import dataclass
from typing import Protocol


class DecisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Choice:
    action_id: str
    controller: str
    reason: str = ""


class Player(Protocol):
    def choose(self, observation: dict) -> Choice: ...


LABELS = {"pass": "过", "ron": "接炮胡", "win": "自摸/杠开胡", "peng": "碰",
          "chi": "吃", "discard": "打", "flower_kong": "单张杠花换牌",
          "an_gang": "四张暗杠", "ming_gang": "接弃牌明杠", "add_gang": "碰后加杠"}


def action_label(action):
    return LABELS[action["kind"]] + " " + " ".join(action["tiles"])
