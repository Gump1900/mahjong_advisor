"""Nonblocking desktop adapter, privacy, stale actions and HTTP boundary."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree

import pytest

from src.players.heuristic import HeuristicPlayer
from src.simulation.engine import Table
from src.simulation.replay import replay, record
from src.simulation.web import ASSETS, DesktopTable, make_handler


def test_initial_view_and_flower_replacement(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path)
    v = d.view()
    assert v["seat"] == 0 and len(v["self"]["hand"]) == 14
    assert v["wall_count"] == 91
    a = next(a for a in v["legal_actions"] if a["kind"] == "flower_kong")
    after = d.action(v["version"], a["id"])
    assert after["wall_count"] == 90 and len(after["self"]["hand"]) == 14
    assert after["self"]["draw_source"] == "replacement"
    assert after["self"]["drawn_tile"] is not None
    assert after["players"][0]["public_flower_hua"] == 1
    with pytest.raises(ValueError, match="过期"):
        d.action(v["version"], a["id"])
    assert d.view() == after


def test_window_frozen_until_human_choice(tmp_path):
    # Seed 42's first genuine optional response is upstream 8p.
    d = DesktopTable(Table(42), output_dir=tmp_path)
    bot = HeuristicPlayer()
    for _ in range(200):
        v = d.view()
        if v["stage"] == "responses":
            break
        d.action(v["version"], bot.choose(v).action_id)
    assert v["stage"] == "responses"
    assert d.table.responses == {}  # No earlier bot choice was applied/leaked.
    before = d.table.state_hash()
    assert d.view() == d.view()
    assert d.table.state_hash() == before
    serialized = json.dumps(v)
    assert "revealed_hands" not in v and "initial_wall" not in serialized
    assert "seed" not in v and "wall" not in v
    assert all("hand" not in p for p in v["players"])
    assert any(s != d.human and choice is not None for s, choice in d.batch)


@pytest.mark.parametrize("human", range(4))
def test_complete_games_and_private_saves(tmp_path, human):
    d = DesktopTable(Table(42), human=human, output_dir=tmp_path)
    bot = HeuristicPlayer()
    for _ in range(600):
        v = d.view()
        if v["stage"] == "ended":
            break
        d.action(v["version"], bot.choose(v).action_id)
    assert v["stage"] == "ended"
    assert sum(v["result"]["net"]) == 0 and len(v["revealed_hands"]) == 4
    assert d.saved.is_file() and d.saved.stat().st_mode & 0o777 == 0o600
    assert replay(json.loads(d.saved.read_text())).state_hash() == d.table.state_hash()
    previous = d.checkpoint()
    assert d.checkpoint() == previous


def test_new_game_preserves_old_and_validates_before_replacing(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path)
    before = d.version
    with pytest.raises(ValueError):
        d.new_game(before, seed=1.2)
    assert d.version == before
    after = d.new_game(before, 43, 1)
    assert after["version"] != before
    saved = list(tmp_path.glob("*.json"))
    assert len(saved) == 1
    assert replay(json.loads(saved[0].read_text())).seed == 42


def test_resume_preserves_full_response_window(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path)
    bot = HeuristicPlayer()
    while d.view()["stage"] != "responses":
        v = d.view()
        d.action(v["version"], bot.choose(v).action_id)
    resumed = DesktopTable(replay(record(d.table)), output_dir=tmp_path)
    assert resumed.view() == d.view()
    v = d.view()
    action = next(a for a in v["legal_actions"] if a["kind"] == "pass")
    assert d.action(v["version"], action["id"]) == resumed.action(v["version"], action["id"])


def test_svg_faces_cover_full_deck():
    from src.simulation.state import full_deck
    names = {"东风": "Ton", "南风": "Nan", "西风": "Shaa", "北风": "Pei",
             "中": "Chun", "发": "Hatsu", "白": "Haku"}
    names.update({t: f"Flower{i+1}" for i, t in enumerate("春夏秋冬梅兰竹菊")})
    names.update({f"{i}{suit}": f"{prefix}{i}" for suit, prefix in [("万", "Man"), ("饼", "Pin"), ("条", "Sou")] for i in range(1, 10)})
    for tile in set(full_deck()):
        root = ElementTree.parse(ASSETS / "tiles" / (names[str(tile)] + ".svg")).getroot()
        assert root.tag.endswith("svg")
        assert not any(e.tag.endswith("script") for e in root.iter())
    assert (ASSETS / "tiles/Back.svg").is_file()


def test_normal_card_sizes_and_natural_row_layout():
    css = (ASSETS / "board-layout.css").read_text()
    html = (ASSETS / "index.html").read_text()
    assert "--card-w:22px" in css and "--card-h:30px" in css
    assert "repeat(6,var(--river-w))" in css
    assert "flex-wrap:wrap" in css and ".meld-faces" in css
    assert html.index('/board-layout.css') > html.index('/table.css')
    assert '/zones.css' not in html and '/square.css' not in html


def test_viewport_layout_keeps_readable_cards_and_separate_zones():
    css = (ASSETS / "board-layout.css").read_text()
    html = (ASSETS / "index.html").read_text()
    assert '/viewport.css' not in html
    assert "calc(100dvh - 80px)" in css
    assert "justify-content:center" in css
    assert "scale(" not in css and "zoom:" not in css
    assert "body.details-open" in css


def test_square_table_uses_one_tile_size_and_true_side_rotations():
    css = (ASSETS / "board-layout.css").read_text()
    html = (ASSETS / "index.html").read_text()
    js = (ASSETS / "table.js").read_text()
    assert '/board-layout.css' in html
    assert "--card-w:22px" in css and "--card-h:30px" in css
    assert "width:var(--card-w); height:var(--card-h)" in css
    assert "rotate(90deg)" in css and "rotate(-90deg)" in css
    assert ".seat-surface" in css and "container-type:size" in css
    assert ".seat-surface .concealed.revealed" in css
    assert "scale(" not in css and "zoom:" not in css
    assert 'class="info-sidebar"' in html and 'class="history-sidebar"' in html
    assert "tableTile(img, true)" in js and "cards.append(tableTile(img))" in js


def test_paced_flower_frames_do_not_jump_wall_or_hand(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    before = d.view()
    with pytest.raises(ValueError, match="真人"):
        d.step(before["version"])
    action = next(a for a in before["legal_actions"] if a["kind"] == "flower_kong")
    result = d.action(before["version"], action["id"])
    flower, draw = result["frames"]
    assert flower["presentation"]["kind"] == "flower_kong"
    assert flower["wall_count"] == 91 and len(flower["self"]["hand"]) == 13
    assert flower["players"][0]["hand_count"] == 13
    assert draw["presentation"]["kind"] == "draw"
    assert draw["wall_count"] == 90 and len(draw["self"]["hand"]) == 14
    assert all(not f["legal_actions"] and not f["can_advance"] for f in result["frames"])
    assert result["awaiting_human"] and result["legal_actions"]
    assert "frames" not in d.view()  # Refresh cannot replay an already-consumed queue.


def test_batch_flowers_keep_unselected_and_do_not_chain_new_flowers(tmp_path):
    from tests.test_simulation import scenario
    table = scenario({0:"1万 2万 3万 4万 5万 6万 1饼 2饼 3饼 南风 南风 东风 中 春"}, wall_tail="夏 秋")
    d = DesktopTable(table, output_dir=tmp_path, paced=True)
    before = d.view()
    result = d.exchange_flowers(before["version"], ["东风", "中"])
    assert result["batch_result"] == {"exchanged":["东风","中"], "drawn":["秋","夏"]}
    assert len(result["self"]["hand"]) == 14 and result["self"]["held_flower_count"] == 3
    assert set(["春","秋","夏"]) <= set(result["self"]["hand"])
    assert result["players"][0]["flowers"] == ["东风","中"]
    assert result["wall_count"] == before["wall_count"]-2
    assert len(d.table.decisions) == 2
    assert len(result["frames"]) == 1 and result["frames"][0]["presentation"]["kind"] == "flower_batch"
    assert result["awaiting_human"] and not result["can_advance"]
    d.table.assert_consistent()


def test_batch_four_same_are_four_singles_not_a_concealed_kong(tmp_path):
    from tests.test_simulation import scenario
    table = scenario({0:"中 中 中 中 1万 2万 3万 4万 5万 6万 1饼 2饼 3饼 南风"})
    d = DesktopTable(table, output_dir=tmp_path, paced=True)
    result = d.exchange_flowers(d.version, ["中"]*4)
    assert len(result["players"][0]["flowers"]) == 4
    assert result["players"][0]["public_flower_hua"] == 6
    assert result["players"][0]["melds"] == []
    assert len(d.table.decisions) == 4


@pytest.mark.parametrize("selection", [[], ["1万"], ["东风"]*5, ["东风", "错误"], "东风", [None], None])
def test_batch_rejects_invalid_selection_without_any_mutation(tmp_path, selection):
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    before = d.table.state_hash()
    with pytest.raises(ValueError):
        d.exchange_flowers(d.version, selection)
    assert d.table.state_hash() == before and not d.table.decisions


def test_batch_requires_wall_and_legal_timing(tmp_path):
    from tests.test_simulation import scenario
    text = "1万 2万 3万 4万 5万 6万 1饼 2饼 3饼 南风 南风 东风 中 春"
    # 空墙：无牌可补 → 拒绝
    d = DesktopTable(scenario({0:text}, empty_wall=True), output_dir=tmp_path, paced=True)
    before = d.table.state_hash()
    with pytest.raises(ValueError):
        d.exchange_flowers(d.version, ["东风","中"])
    assert d.table.state_hash() == before
    # 2026-11-18 用户定稿：吃/碰接管的回合仍可换花 → claim 时点不再拒绝
    d = DesktopTable(scenario({0:text}, can_kong=False, source="claim"),
                     output_dir=tmp_path, paced=True)
    d.exchange_flowers(d.version, ["东风", "中"])          # 不抛错即通过
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    v = d.view()
    a = next(a for a in v["legal_actions"] if a["kind"] == "discard")
    d.action(v["version"], a["id"])
    before = d.table.state_hash()
    with pytest.raises(ValueError):
        d.exchange_flowers(d.version, ["东风"])
    assert d.table.state_hash() == before


def test_batch_has_normal_replayable_actions_and_stale_protection(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    old = d.version
    d.exchange_flowers(old, ["东风","中","春"])
    assert replay(record(d.table)).state_hash() == d.table.state_hash()
    before = d.table.state_hash()
    with pytest.raises(ValueError, match="过期"):
        d.exchange_flowers(old,["东风"])
    assert before == d.table.state_hash()


@pytest.mark.parametrize("seat", range(4))
def test_referee_batch_exchange_is_seat_independent(tmp_path, seat):
    from tests.test_simulation import scenario
    table = scenario({seat:"1万 2万 3万 4万 5万 6万 1饼 2饼 3饼 南风 南风 东风 中 春"},
                     actor=seat, wall_tail="夏 秋")
    before = len(table.wall)
    assert table.exchange_flowers(seat,["东风","中"],controller="test:any-seat") == ["秋","夏"]
    assert len(table.seats[seat].hand) == 14 and len(table.wall) == before-2
    assert [str(t) for t in table.seats[seat].flowers] == ["东风","中"]
    assert any(str(t)=="春" for t in table.seats[seat].hand)
    table.assert_consistent()


@pytest.mark.parametrize("seat", [1,2,3])
def test_bot_batch_animation_has_no_private_replacements(tmp_path, seat):
    from tests.test_simulation import scenario
    table = scenario({seat:"1万 2万 3万 4万 5万 6万 1饼 2饼 3饼 南风 南风 东风 中 春"},
                     actor=seat, wall_tail="夏 秋")
    d = DesktopTable(table, output_dir=tmp_path, paced=True)
    result = d.step(d.version)
    assert len(result["frames"]) == 1
    event = result["frames"][0]["presentation"]
    assert event["kind"] == "flower_batch" and event["seat"] == seat
    assert len(event["tiles"]) == 3 and event["drawn_count"] == 3
    assert "drawn_tiles" not in event and "batch_result" not in result
    assert all("tile" not in e and e["hidden"] for e in result["events"] if e["kind"]=="draw")
    assert result["players"][seat]["hand_count"] == 14


def test_tenpai_tiles_and_discard_preview_are_real_scoring(tmp_path):
    from tests.test_simulation import scenario
    from src.simulation.observation import observe
    hand = "1万 2万 3万 4万 5万 6万 7条 8条 9条 南风 南风 南风 西风"
    table = scenario({0:hand}, actor=1)
    data = observe(table,0)["self"]
    assert [w["tile"] for w in data["waiting_tiles"]] == ["西风"]
    w = data["waiting_tiles"][0]
    assert w["can_ron"] and w["ron_hua"] == 3 and w["self_draw_hua"] == 5
    table.seats[0].ron_blocked=True
    assert not observe(table,0)["self"]["waiting_tiles"][0]["can_ron"]
    assert "过胡未过圈" in observe(table,0)["self"]["waiting_tiles"][0]["reason"]
    table2=scenario({0:hand+" 9饼"},actor=0)
    preview=observe(table2,0)["self"]
    assert not preview["waiting_tiles"]
    assert [w["tile"] for w in preview["discard_waits"]["9饼"]] == ["西风"]


def test_no_flower_tenpai_only_self_draw_and_held_flowers_not_ready(tmp_path):
    from tests.test_simulation import scenario
    from src.simulation.observation import observe
    hand="1万 2万 3万 4万 5万 6万 7条 8条 9条 1饼 2饼 3饼 西风"
    t=scenario({0:hand},actor=1)
    waits=observe(t,0)["self"]["waiting_tiles"]
    assert waits and all(not w["can_ron"] and w["self_draw_hua"]==6 for w in waits)
    assert all("无资格花" in w["reason"] for w in waits)
    t=scenario({0:hand.replace("西风","中")},actor=1)
    assert not observe(t,0)["self"]["waiting_tiles"]
    assert not observe(t,0)["self"]["discard_waits"]


def test_wait_counts_do_not_read_other_hands(tmp_path):
    from tests.test_simulation import scenario
    from src.simulation.observation import observe
    hand="1万 2万 3万 4万 5万 6万 7条 8条 9条 南风 南风 南风 西风"
    t=scenario({0:hand},actor=1)
    first=observe(t,0)["self"]["waiting_tiles"]
    assert first[0]["unseen"]==3
    # Move every remaining west into an opponent's private hand, swapping equal
    # counts back into the wall: observer's unseen estimate must not change.
    west = next(x for x in t.seats[0].hand if str(x)=="西风")
    for seat in range(1,4):
        if west in t.wall:
            old=t.seats[seat].hand[0];t.wall.remove(west)
            t.wall.append(old);t.seats[seat].hand[0]=west
    assert observe(t,0)["self"]["waiting_tiles"]==first


def test_waits_do_not_deduct_unknown_kong_and_do_not_suggest_own_fifth_copy():
    from tests.test_simulation import scenario
    from src.simulation.observation import observe
    hand="1条 3条 1万 2万 3万 4饼 5饼 6饼 7万 8万 9万 南风 南风"
    table=scenario({0:hand},actor=1,melds={1:[("an_gang","2条 2条 2条 2条")]})
    waits=observe(table,0)["self"]["waiting_tiles"]
    assert next(w for w in waits if w["tile"]=="2条")["unseen"]==4
    # Same shape with the four copies in OUR known kong: a fifth copy is illegal.
    short="1条 3条 1万 2万 3万 4饼 5饼 6饼 南风 南风"
    table=scenario({0:short},actor=1,melds={0:[("an_gang","2条 2条 2条 2条")]})
    assert not observe(table,0)["self"]["waiting_tiles"]


def test_paced_discard_does_not_play_three_bots_at_once(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    v = d.view()
    action = next(a for a in v["legal_actions"] if a["kind"] == "discard")
    after = d.action(v["version"], action["id"])
    assert len(d.table.decisions) == 1 and after["wall_count"] == 91
    assert after["can_advance"] and not after["awaiting_human"]
    draw = d.step(after["version"])
    assert draw["wall_count"] == 90 and draw["actor"] == 1
    assert draw["players"][1]["hand_count"] == 14
    event = draw["frames"][-1]["presentation"]
    assert event["kind"] == "draw" and event["hidden"] and "tile" not in event
    assert not draw["players"][1]["river"]
    before_hash = d.table.state_hash()
    with pytest.raises(ValueError, match="过期"):
        d.step(after["version"])
    assert d.table.state_hash() == before_hash


def test_hidden_kong_animation_never_reveals_identity(tmp_path):
    from tests.test_simulation import scenario
    table = scenario({1: "1万 1万 1万 1万 2万 3万 4万 5饼 6饼 7饼 南风 西风 北风 中"}, actor=1)
    d = DesktopTable(table, output_dir=tmp_path, paced=True)
    result = d.step(d.version)
    kong, draw = result["frames"]
    assert kong["presentation"] == {"kind": "an_gang", "seat": 1, "hidden": True}
    assert kong["players"][1]["hand_count"] == 10
    assert draw["players"][1]["hand_count"] == 11
    assert kong["players"][1]["melds"][-1] == {"type":"an_gang", "size":4, "tiles":None, "hidden":True}
    assert kong["wall_count"] == result["wall_count"] + 1
    assert "1万" not in json.dumps(result, ensure_ascii=False)
    assert draw["presentation"]["hidden"] and "tile" not in draw["presentation"]


@pytest.mark.parametrize("seed", [42, 43, 44, 45, 46, 47])
def test_paced_full_games_match_unpaced_and_reveal_only_at_end(tmp_path, seed):
    d = DesktopTable(Table(seed, game_id=f"equivalence-{seed}"), output_dir=tmp_path, paced=True)
    bot = HeuristicPlayer()
    kinds = set()
    for _ in range(2000):
        v = d.view()
        if v["stage"] == "ended":
            break
        if v["awaiting_human"]:
            r = d.action(v["version"], bot.choose(v).action_id)
        else:
            r = d.step(v["version"])
        for frame in r["frames"]:
            kinds.add(frame["presentation"]["kind"])
            if frame["stage"] != "ended":
                assert "revealed_hands" not in frame
                for p in frame["players"]:
                    if p["seat"] != frame["seat"]:
                        for m in p["melds"]:
                            if m["type"] == "an_gang":
                                assert m["tiles"] is None and m["hidden"]
            if frame["presentation"]["kind"] == "win":
                assert frame["result"] is None
            if frame["presentation"]["kind"] in ("peng", "chi", "ming_gang"):
                assert frame["players"][frame["actor"]]["hand_count"] == len(d.table.seats[frame["actor"]].hand) - int(frame["presentation"]["kind"] == "ming_gang")
    assert v["stage"] == "ended" and len(v["revealed_hands"]) == 4
    assert all(not m["hidden"] for p in v["players"] for m in p["melds"])
    assert {"discard", "draw"} <= kinds
    auto = DesktopTable(Table(seed, game_id=f"equivalence-{seed}"), output_dir=tmp_path)
    for _ in range(600):
        view = auto.view()
        if view["stage"] == "ended":
            break
        auto.action(view["version"], bot.choose(view).action_id)
    assert auto.table.state_hash() == d.table.state_hash()


def test_frontend_selection_and_pacing():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for actual frontend regression")
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
function element() { const classes=new Set(); const self={children:[],dataset:{},className:'',disabled:false,hidden:false,
 classList:{toggle(n,on){if(on)classes.add(n);else classes.delete(n)},add(n){classes.add(n)},remove(n){classes.delete(n)},contains(n){return classes.has(n)}},
 append(...x){self.children.push(...x)},replaceChildren(...x){self.children=x},setAttribute(k,v){self[k]=v},addEventListener(){},
 querySelector:()=>null,insertBefore(x){self.children.push(x)},parentNode:null};
 return self; }
const intervals=[];let clock=0;
const ctx=vm.createContext({console,performance:{now:()=>clock},setInterval:f=>intervals.push(f),setTimeout:()=>0,clearTimeout(){},
 localStorage:{getItem:()=>null,setItem(){}},fetch:()=>new Promise(()=>{}),
 document:{hidden:false,body:element(),createElement:element,createTextNode:t=>t,
 getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},querySelector:()=>element()}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext(`
let sent=[];
run=(path,extra)=>{sent.push({path,extra})};
state={awaiting_human:true,self:{hand:['1万','1万','2万'],held_flower_count:0,drawn_tile:null},legal_actions:[{id:'a',kind:'discard',tiles:['1万']},{id:'b',kind:'discard',tiles:['2万']}],stage:'turn'};
live=state; renderHand();
`,ctx);
elements.get('hand').children[0].onclick();
assert.equal(vm.runInContext('selected.key',ctx),'0');
assert.equal(elements.get('hand').children.filter(b=>b.classList.contains('selected')).length,1);
elements.get('hand').children[1].onclick();
assert.equal(vm.runInContext('selected.key',ctx),'1');
assert.equal(vm.runInContext('sent.length',ctx),0); // Same kind, DIFFERENT physical card only switches selection.
elements.get('hand').children[1].onclick();
assert.equal(vm.runInContext('sent.length',ctx),1);
assert.equal(vm.runInContext('sent[0].extra.action_id',ctx),'a');
vm.runInContext(`
sent=[];selected=null;flowerMode=true;
state={awaiting_human:true,wall_count:30,self:{hand:['东风','中','中','春','1万'],held_flower_count:4,drawn_tile:null},legal_actions:[{id:'f1',kind:'flower_kong',tiles:['东风']},{id:'f2',kind:'flower_kong',tiles:['中']},{id:'f3',kind:'flower_kong',tiles:['春']},{id:'d',kind:'discard',tiles:['1万']}],stage:'turn'};
renderHand();renderActions();
`,ctx);
assert.equal(elements.get('hand').children[4].disabled,true);
elements.get('hand').children[0].onclick();
elements.get('hand').children[1].onclick();
assert.equal(vm.runInContext('flowerKeys.size',ctx),2);
assert.equal(elements.get('hand').children.filter(b=>b.classList.contains('selected')).length,2);
assert.match(elements.get('actions').children[0].textContent,/选中 2 张.*保留 2 张/);
elements.get('actions').children[3].onclick();
assert.equal(vm.runInContext('sent[0].path',ctx),'/api/flowers');
assert.equal(vm.runInContext("JSON.stringify(sent[0].extra.tiles)",ctx),'["东风","中"]');
elements.get('actions').children[1].onclick();
assert.equal(vm.runInContext('flowerKeys.size',ctx),4);
elements.get('hand').children[2].onclick();
assert.equal(vm.runInContext('flowerKeys.size',ctx),3); // Keep exactly one of two identical flowers.
vm.runInContext(`
playing=true;state={seat:0,presentation:{kind:'flower_batch',seat:1,tiles:['东风','中','春'],drawn_count:3}};
renderMotion();
`,ctx);
assert.equal(elements.get('motion').children[0].textContent,'下家 · 连续换花 3 张');
const incoming=elements.get('motion').children[2].children.filter(x=>x.src);
assert.equal(incoming.length,3);
assert.ok(incoming.every(x=>x.src==='/tiles/Back.svg')); // Opponent replacements never become faces.
vm.runInContext(`sent=[];live={can_advance:true};playing=false;remaining=100;paused=true;`,ctx);
clock+=200;intervals[0]();assert.equal(vm.runInContext('sent.length',ctx),0);
vm.runInContext(`paused=false;speed='step';`,ctx);
clock+=200;intervals[0]();assert.equal(vm.runInContext('sent.length',ctx),0);
vm.runInContext(`advancePhase(true)`,ctx);assert.equal(vm.runInContext('sent[0].path',ctx),'/api/step');
vm.runInContext(`sent=[];speed='normal';remaining=100;`,ctx);
ctx.document.hidden=true;clock+=200;intervals[0]();assert.equal(vm.runInContext('sent.length',ctx),0);
ctx.document.hidden=false;clock+=200;intervals[0]();assert.equal(vm.runInContext('sent.length',ctx),1);
vm.runInContext(`sent=[];live={can_advance:false};`,ctx);
clock+=200;intervals[0]();assert.equal(vm.runInContext('sent.length',ctx),0); // Never time out a human choice.
'''
    result = subprocess.run([node, "-e", script, str(ASSETS / "table.js")], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_http_privacy_assets_and_write_guard(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(d))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(url + "/api/state") as r:
            v = json.load(r)
        with urllib.request.urlopen(url + "/tiles/Man1.svg") as r:
            assert r.headers["Content-Type"] == "image/svg+xml"
        for route in ("/../engine.py", "/%2e%2e/engine.py", "/runs/mahjong/x.json"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + route)
            assert error.value.code == 404
        action = v["legal_actions"][0]
        payload = json.dumps({"version": v["version"], "action_id": action["id"]}).encode()
        bad = urllib.request.Request(url + "/api/action", payload, {"Content-Type": "application/json", "Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(bad)
        assert error.value.code == 403 and d.version == v["version"]
        good = urllib.request.Request(url + "/api/action", payload, {"Content-Type": "application/json"})
        with urllib.request.urlopen(good) as r:
            assert json.load(r)["version"] != v["version"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
