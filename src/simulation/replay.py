"""Private full-information records; replay never invokes any player/API."""
import json
import copy
import os
from pathlib import Path

from ..core.tiles import parse_tile
from .engine import Table
from .state import SUPPORTED_RULES_VERSIONS


def record(table):
    return {"format_version": 1, "rules_version": table.rules_version,
            "draw_convention": "front-normal-back-replacement-no-dead-wall",
            "seed": table.seed, "dealer": table.dealer, "game_id": table.game_id,
            "metadata": copy.deepcopy(table.metadata),
            "initial_wall": [str(t) for t in table.initial_wall],
            "decisions": list(table.decisions), "final_state_hash": table.state_hash(),
            "final_state": table.snapshot(),
            "privacy": "裁判全知牌谱：含四家私牌与未来牌墙，严禁发给对局中的玩家或LLM"}


def save(table, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an existing replay accidentally.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record(table), stream, ensure_ascii=False, indent=2)
    return path


def replay(data):
    if (data.get("format_version") != 1 or data.get("rules_version") not in SUPPORTED_RULES_VERSIONS
            or data.get("draw_convention") != "front-normal-back-replacement-no-dead-wall"):
        raise ValueError("不支持的牌谱或规则版本")
    table = Table(data["seed"], data["dealer"], game_id=data["game_id"],
                  wall=[parse_tile(t) for t in data["initial_wall"]], rules_version=data["rules_version"])
    table.metadata = copy.deepcopy(data.get("metadata", {}))
    for index, item in enumerate(data["decisions"]):
        table.apply(item["seat"], item["action"]["id"],
                    controller=item.get("controller", "replay"), reason=item.get("reason", ""))
        if (table.decisions[-1]["action"] != item["action"]
                or table.state_hash() != item["state_hash"]):
            raise ValueError(f"第{index+1}个动作重放不一致")
    if table.state_hash() != data["final_state_hash"] or table.snapshot() != data["final_state"]:
        raise ValueError("最终局面重放不一致")
    return table
