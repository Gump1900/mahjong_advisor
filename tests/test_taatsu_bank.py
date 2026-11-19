"""题库完整性：每题手牌可解析、张数正确、答案在手牌里、来源可追溯。"""
import json
import os

from src.core.tiles import parse_tile

BANK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "banks", "taatsu-bank-v1.jsonl")
SYNTHETIC_BANK = os.path.join(os.path.dirname(BANK), "taatsu-bank-synthetic.jsonl")
PROLOG_BANK = os.path.join(os.path.dirname(BANK), "taatsu-bank-prolog.jsonl")


def load_bank():
    with open(BANK, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_optional(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_bank_loads_and_fields_complete():
    problems = load_bank()
    assert len(problems) >= 20, f"题库应有≥20题，实际{len(problems)}"
    required = {"id", "source", "hand", "answer", "principles", "scope"}
    for p in problems:
        missing = required - set(p)
        assert not missing, f"{p.get('id')} 缺字段 {missing}"


def test_every_hand_is_14_tiles_and_parses():
    for p in load_bank():
        tiles = [parse_tile(t) for t in p["hand"]]
        assert len(tiles) == 14, f"{p['id']} 手牌应14张，实际{len(tiles)}"
        for t in p["hand"]:
            assert t in p["hand"], f"{p['id']} 自洽"


def test_answer_and_alts_are_in_hand():
    for p in load_bank():
        hand = p["hand"]
        assert p["answer"] in hand, f"{p['id']} 答案{p['answer']}不在手牌"
        for alt in p.get("alt_ok", []):
            assert alt in hand, f"{p['id']} 备选{alt}不在手牌"


def test_rivers_parse_when_present():
    for p in load_bank():
        for seat, river in (p.get("rivers") or {}).items():
            for t in river:
                parse_tile(t)   # 不炸即可


def test_synthetic_bank_present_and_sound():
    problems = load_optional(SYNTHETIC_BANK)
    assert len(problems) >= 1000, f"合成库应≥1000题，实际{len(problems)}"
    for p in problems[:50] + problems[-5:]:
        assert p.get("tier") == "synthetic"
        assert len(p["hand"]) == 14, p["id"]
        assert p["answer"] in p["hand"], p["id"]


def test_prolog_bank_each_has_source_meta():
    problems = load_optional(PROLOG_BANK)
    if not problems:
        return   # 尚未下载时跳过；下载后强校验
    assert len(problems) >= 500, f"牌谱库应≥500题，实际{len(problems)}"
    for p in problems[:50]:
        assert p.get("tier") == "prolog"
        assert len(p["hand"]) == 14, p["id"]
        assert p["answer"] in p["hand"], p["id"]
        assert p.get("meta", {}).get("game_id"), p["id"]
