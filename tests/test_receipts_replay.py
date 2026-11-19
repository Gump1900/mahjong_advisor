"""Receipt persistence and dual-channel replay review tests."""
import json
import os

import pytest

from src.decision.ev import CandidateEV
from src.decision.receipts import load_receipts, save_receipt
from src.core.tiles import parse_tile


def _cand(tile, ev):
    return CandidateEV(tile=parse_tile(tile), ev=ev, p_win_next=0.1,
                       v_win=12.0, p_point=0.05, p_lo=0.02, p_hi=0.1,
                       v_deal=8.0, exp_neff_1ply=16.0, exp_neff_exact=True,
                       labels=["先验采样N=16"])


def test_roundtrip_and_append(tmp_path):
    root = str(tmp_path / "receipts")
    path1 = save_receipt("gameA", 1, [_cand("9条", 1.5), _cand("5条", 1.2)], root=root)
    path2 = save_receipt("gameA", 2, [_cand("1万", 0.8)], root=root)
    assert path1 == path2
    assert os.path.basename(path1) == "gameA.jsonl"
    loaded = load_receipts("gameA", root=root)
    assert [r["revision"] for r in loaded] == [1, 2]
    assert loaded[0]["candidates"][0]["tile"] == "9条"
    assert loaded[0]["candidates"][0]["ev"] == 1.5
    assert loaded[1]["candidates"][0]["tile"] == "1万"


def test_missing_game_returns_empty(tmp_path):
    assert load_receipts("nope", root=str(tmp_path)) == []


def test_receipt_is_jsonl(tmp_path):
    root = str(tmp_path / "receipts")
    save_receipt("g", 1, [_cand("9条", 1.0)], root=root)
    with open(os.path.join(root, "g.jsonl"), encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    assert len(lines) == 1
    assert lines[0]["game_id"] == "g"


# --- 复盘双通道 --------------------------------------------------------------------
from src.decision.replay_review import dual_review

WAITING_13 = "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条"
OTHER_13 = "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼"


def _receipt(revision, tile, p_point):
    return {"game_id": "g", "revision": revision,
            "candidates": [{"tile": tile, "ev": 1.0, "p_point": p_point,
                            "p_lo": p_point, "p_hi": p_point, "v_deal": 0.0,
                            "labels": []}]}


FULL_TRUTH = {
    "left": WAITING_13.split(),
    "opposite": OTHER_13.split(),
    "right": OTHER_13.split(),
}


class TestDualReview:
    def test_full_truth_makes_p_fact_0_or_1(self):
        # 推荐打 5条：left 真身在听 5条 → 真值 1；delta = prior - 1
        review = dual_review([_receipt(1, "5条", 0.25)], FULL_TRUTH)
        assert review[0]["true_p"] == 1
        assert review[0]["delta"] == pytest.approx(0.25 - 1)

    def test_safe_recommendation_true_zero(self):
        review = dual_review([_receipt(1, "9条", 0.25)], FULL_TRUTH)
        assert review[0]["true_p"] == 0
        assert review[0]["delta"] == pytest.approx(0.25)

    def test_partial_truth_gives_none(self):
        review = dual_review([_receipt(1, "5条", 0.25)],
                             {"left": WAITING_13.split()})
        assert review[0]["true_p"] is None
        assert review[0]["delta"] is None

    def test_no_truth_gives_none(self):
        review = dual_review([_receipt(1, "5条", 0.25)], None)
        assert review[0]["true_p"] is None

    def test_multiple_receipts_in_order(self):
        receipts = [_receipt(1, "5条", 0.2), _receipt(2, "9条", 0.1)]
        review = dual_review(receipts, FULL_TRUTH)
        assert [r["revision"] for r in review] == [1, 2]
        assert [r["true_p"] for r in review] == [1, 0]


class TestDualReviewMeldedTruth:
    def test_melded_opponent_tenpai_counted(self):
        # 对家 4 副露 + 单吊 9万：真值必须按 fuuro=4 判听，而不是当 13 张
        truth = {
            "left": {"hand": OTHER_13.split(), "melds": 0},
            "opposite": {"hand": ["9万"], "melds": 4},
            "right": {"hand": OTHER_13.split(), "melds": 0},
        }
        review = dual_review([_receipt(1, "9万", 0.3)], truth)
        assert review[0]["true_p"] == 1

    def test_plain_list_truth_still_works(self):
        review = dual_review([_receipt(1, "5条", 0.25)], FULL_TRUTH)
        assert review[0]["true_p"] == 1
