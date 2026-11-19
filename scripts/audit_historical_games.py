"""Offline historical corpus audit. No model calls, training or strategy edits.

Counts completed games once by game_id, not resumed attempts. Oracle labels
are used only to identify committed proposals, never to recommend an action.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.players.tactical_facts import flower_opportunities
from src.simulation.replay import replay


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def audit(base):
    games = {}
    for parent in (base / "self-play", base / "live-batch"):
        for path in sorted(parent.rglob("referee-private.json")):
            record = read(path)
            if record["final_state"]["stage"] != "ended":
                continue
            old = games.get(record["game_id"])
            if old is None or len(record["decisions"]) > len(old[1]["decisions"]):
                games[record["game_id"]] = (path, record)
    groups = {}
    replay_errors = []
    walls_by_type = {kind:set() for kind in ("llm","search","heuristic")}
    for gid, (path, record) in games.items():
        root = next(p for p in path.parents if p.parent.name in ("self-play", "live-batch"))
        name = str(root)
        kind=("llm" if any(d["controller"].startswith("llm") for d in record["decisions"]) else
              "search" if any(d["controller"].startswith("search") for d in record["decisions"]) else "heuristic")
        walls_by_type[kind].add(hashlib.sha256(json.dumps(record["initial_wall"]).encode()).hexdigest())
        group = groups.setdefault(name, {"games":0,"controllers":Counter(),"methods":Counter(),
            "walls":set(),"replayed":0,"snapshots":[],"counts":Counter(),"intent":Counter(),
            "priorities":Counter(),"confidence":Counter(),"tools":Counter(),"flower_examples":[]})
        group["games"] += 1
        group["snapshots"].append(str(path))
        group["walls"].add(hashlib.sha256(json.dumps(record["initial_wall"]).encode()).hexdigest())
        group["controllers"].update(d["controller"] for d in record["decisions"])
        group["methods"][record["final_state"]["result"]["method"]] += 1
        try:
            table = replay(record)
            assert table.stage == "ended" and table.result == record["final_state"]["result"]
            group["replayed"] += 1
        except Exception as exc:
            replay_errors.append({"file":str(path),"error":str(exc),"type":type(exc).__name__})
        if not any(d["controller"].startswith("llm") for d in record["decisions"]):
            continue
        folder = path.parent.parent
        if not (folder/"completed-decisions.jsonl").exists():
            raise ValueError(f"Missing canonical decisions: {folder}")
        rows = lines(folder/"completed-decisions.jsonl")
        labels = {r["observation_id"]:r for r in lines(folder/"completed-labels-offline-only.jsonl")}
        committed = {d["action"]["id"] for d in record["decisions"]}
        seen = set()
        for row in rows:
            obs = row["observation"];choice = row["choice"]
            if obs["observation_id"].split(":",1)[0] != gid or choice.get("controller") != "llm":
                continue
            key = (obs["observation_id"],choice["action_id"])
            if key in seen:
                continue
            seen.add(key);count=group["counts"]
            count["accepted_proposals"] += 1
            label=labels.get(obs["observation_id"],{})
            executed=choice["action_id"] in committed
            if "selected_action_executed" in label:
                assert executed == label["selected_action_executed"]
            count["executed_proposals"] += int(executed)
            validation=row.get("decision_validation",{})
            note=validation.get("decision_note")
            for tool in validation.get("tool_trace",[]):
                group["tools"][tool.get("request",tool).get("name","unknown")] += 1
            if note:
                count["proposals_with_opponent_notes"] += 1
                for target in note.get("opponents",[]):
                    count["opponent_notes"] += 1
                    group["confidence"][str(target.get("confidence","unspecified"))] += 1
                    if note.get("version")=="strategy-v2":
                        count["typed_opponent_notes"] += 1
                        count["typed_notes_with_patterns"] += bool(target.get("patterns"))
                        count["typed_notes_with_watch_tiles"] += bool(target.get("watch_tiles"))
            reasoning=validation.get("reasoning",{})
            if isinstance(reasoning,dict) and reasoning:
                group["intent"][reasoning.get("intent","missing")] += 1
                group["priorities"].update(reasoning.get("priorities",[]))
                count["proposals_with_focus"] += bool(reasoning.get("focus_seats"))
            chosen=next(c for c in row["analysis"]["candidates"] if c["action_id"]==choice["action_id"])
            if chosen["kind"]=="discard":
                count["discard_proposals"] += 1
                options=[c for c in row["analysis"]["candidates"] if c["kind"]=="discard"]
                ties=[c for c in options if c["action_id"]!=chosen["action_id"] and
                      c["shanten"]==chosen["shanten"] and c["unseen_improving"]==chosen["unseen_improving"]]
                count["discards_with_equal_shanten_and_outs_alternative"] += bool(ties)
                count["discards_with_identical_improving_tile_set_alternative"] += any(
                    set(c.get("improving_tiles",[]))==set(chosen.get("improving_tiles",[])) for c in ties)
                count["discards_above_min_shanten"] += chosen["shanten"]>min(c["shanten"] for c in options)
            if executed and obs["stage"]=="turn":
                opportunities=[o for o in flower_opportunities(obs) if o["immediate_gangkai"]]
                if opportunities:
                    taken=any(o["action_id"]==choice["action_id"] for o in opportunities)
                    count["immediate_flower_opportunity_observations"] += 1
                    count["immediate_flower_opportunity_selected"] += taken
                    if not taken:
                        group["flower_examples"].append({"observation_id":obs["observation_id"],
                            "choice":choice,"opportunities":opportunities,"file":str(folder/"completed-decisions.jsonl")})
    for group in groups.values():
        group["distinct_wall_hashes"]=len(group.pop("walls"))
        group["type"]=("llm" if any(c.startswith("llm") for c in group["controllers"]) else
                         "search" if any(c.startswith("search") for c in group["controllers"]) else "heuristic")
    return {"scope":"local historical audit only; no API, no model updates, no hindsight action recommendation",
            "completed_game_ids":len(games),"completed_by_type":dict(Counter({kind:sum(g['games'] for g in groups.values() if g['type']==kind)
                for kind in ('llm','search','heuristic')})),
            "distinct_walls_by_type":{kind:len(walls) for kind,walls in walls_by_type.items()},
            "replay_errors":replay_errors,"batches":groups}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs",type=Path,default=Path("runs"))
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=audit(args.runs)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!='batches'},ensure_ascii=False))
    for name,batch in result['batches'].items():
        print(json.dumps({"batch":name,**{k:v for k,v in batch.items() if k not in ('snapshots','flower_examples')}},ensure_ascii=False))
