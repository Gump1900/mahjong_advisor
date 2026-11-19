"""桌面 UI 注入层：副露"被拿的那张"记号 + 左侧常驻听牌面板。

红线遵守：不改 simulation/ —— 由 ev_table 在 HTTP 出口对【运行时副本】打补丁，
本模块只提供：/api/state 富化（claimed 字段）+ 静态资源改写 + 面板资源。
"""
from src.webapp.table_ui_patch import (
    PANEL_CSS, PANEL_JS, enrich_state, patch_index, patch_tablejs)


def _payload():
    return {
        "seat": 0, "stage": "turn",
        "self": {"waiting_tiles": [{"tile": "3条", "unseen": 2, "can_ron": True,
                                    "reason": "两面"}],
                 "structural_shanten": 0},
        "players": [
            {"seat": 0, "melds": []},
            {"seat": 1, "melds": [
                {"type": "chi", "tiles": ["2条", "3条", "4条"], "size": 3,
                 "source": 2, "call_number": 1},
                {"type": "an_gang", "tiles": ["5饼"] * 4, "size": 4},
            ]},
            {"seat": 2, "melds": []},
            {"seat": 3, "melds": [
                {"type": "ming_gang", "tiles": ["9万"] * 4, "size": 4,
                 "source": 0, "call_number": 1},
            ]},
        ],
        "events": [
            {"kind": "discard", "seat": 2, "tile": "3条"},
            {"kind": "chi", "seat": 1, "source": 2,
             "tiles": ["2条", "3条", "4条"]},
            {"kind": "an_gang", "seat": 1, "tile": "5饼"},
            {"kind": "discard", "seat": 0, "tile": "9万"},
            {"kind": "peng", "seat": 3, "source": 0,
             "tiles": ["9万", "9万", "9万"]},
            {"kind": "add_gang", "seat": 3, "tile": "9万"},
        ],
    }


class TestEnrichState:
    def test_chi_claimed_is_the_discarded_tile(self):
        out = enrich_state(_payload())
        meld = out["players"][1]["melds"][0]
        assert meld["claimed"] == "3条"          # 吃的是上家打的那张

    def test_an_gang_has_no_claim(self):
        out = enrich_state(_payload())
        assert out["players"][1]["melds"][1]["claimed"] is None

    def test_peng_then_add_gang_still_marked(self):
        out = enrich_state(_payload())
        assert out["players"][3]["melds"][0]["claimed"] == "9万"

    def test_missing_discard_history_degrades_to_none(self):
        payload = _payload()
        payload["events"] = [e for e in payload["events"]
                             if not (e["kind"] == "discard" and e["seat"] == 2)]
        out = enrich_state(payload)
        assert out["players"][1]["melds"][0]["claimed"] is None

    def test_idempotent(self):
        once = enrich_state(_payload())
        assert enrich_state(once) == once


class TestAssetPatch:
    def test_index_gets_panel_assets_and_original_untouched(self, tmp_path):
        original = open(_asset("index.html"), encoding="utf-8").read()
        patched = patch_index(original)
        assert "/ui-panel.js" in patched and "/ui-panel.css" in patched
        assert open(_asset("index.html"), encoding="utf-8").read() == original
        assert patch_index(patched) == patched          # 幂等

    def test_tablejs_marks_claimed_and_shows_chi_source(self):
        original = open(_asset("table.js"), encoding="utf-8").read()
        patched, applied = patch_tablejs(original)
        assert applied == {"claimed_tile": True, "chi_source": True}
        assert "claimed-tile" in patched
        assert 'meld.type!=="chi"' not in patched        # 吃也显示来源
        assert patched != original
        # 原文件未被写回
        assert open(_asset("table.js"), encoding="utf-8").read() == original

    def test_panel_resources_present(self):
        assert "info-sidebar" in PANEL_JS and "waiting_tiles" in PANEL_JS
        assert "claimed-tile" in PANEL_CSS

    def test_no_banner_actions_float_center_and_independent_polling(self):
        """不要大红横幅：动作按钮本身上浮居中即提示；面板自取状态。"""
        assert "ui-await-banner" not in PANEL_JS          # 横幅撤销（用户2026-11-18）
        assert "ui-pulse" not in PANEL_CSS                # 不要乱动的动画
        assert "awaiting-call" in PANEL_JS
        assert ":has(button)" in PANEL_CSS                # 空按钮条不上浮（空横幅bug）
        assert '"/api/state"' in PANEL_JS                 # 面板独立拉取
        assert "event-pass" in PANEL_CSS                  # 过牌动作提示不再弹空黑框

    def test_waits_belong_to_own_hand_not_viewport_top(self):
        """本人待牌复用手牌区，不再在对家牌上方生成第二个浮层。"""
        assert "ui-tenpai-badge" not in PANEL_JS + PANEL_CSS
        css = open(_asset("board-layout.css"), encoding="utf-8").read()
        assert ".hand-dock #waits{position:absolute;left:0;right:auto" in css
        assert ".dock-tools .actions{position:absolute;left:50%" in css

    def test_meld_claims_use_rotation_position_encoding(self):
        """用户定稿（2026-11-18）：横放牌+位置编码来源——左=上家中=对家右=下家；
        吃恒为上家(左)。无动画无彩色框。"""
        assert "rotate" in PANEL_CSS                          # 横放回归
        assert "ui-pulse" not in PANEL_CSS
        assert "src-" not in PANEL_CSS.replace("src=", "")   # 来源配色撤销

    def test_seat_info_no_overlap_fix(self):
        assert "player-heading" in PANEL_CSS      # 座位信息加底垫防重叠


def _asset(name):
    import os
    from src.simulation.web import ASSETS
    return os.path.join(str(ASSETS), name)
