"""Public-feature empirical opponent baseline, trained offline only.

Shrunk binomial tables are deliberately auditable. Self-play labels describe a
weak policy distribution, not human skill. Inference remains shadow-only.
"""
import json
from pathlib import Path


VERSION = "public-opponent-baseline-v1"
DEFAULT_MODEL = Path(__file__).resolve().parents[2]/"runs/models/opponent-public-v1.json"


def features(obs, seat):
    p = obs["players"][seat]
    discards = sum(e["kind"] == "discard" and e["seat"] == seat for e in obs["events"])
    suits = {t[-1] for m in p["melds"] for t in (m["tiles"] or []) if t[-1] in "万饼条"}
    focus = next(iter(suits)) if len(suits) == 1 else "mixed" if suits else "none"
    coarse = [len(p["melds"]), min(5,discards//3)]
    fine = coarse+[min(4,p["known_qualifying_hua"]["total"]//3), p["unknown_ankan_count"],focus]
    return json.dumps(coarse), json.dumps(fine,ensure_ascii=False)


def _counter():
    return {"n": 0, "ready": 0, "waits": {}}


def _add(counter, target):
    counter["n"] += 1
    counter["ready"] += int(target["structural_tenpai"])
    for tile in set(target["structural_waits"]):
        counter["waits"][tile] = counter["waits"].get(tile,0)+1


def predict(model, obs, seat):
    if model.get("version") != VERSION or obs["rules_version"] not in model["rules_versions"]:
        raise ValueError("对手模型版本不匹配")
    coarse,fine = features(obs,seat)
    global_ = model["global"]
    ready = global_["ready"]/global_["n"]
    tiles = {tile:n/global_["n"] for tile,n in global_["waits"].items()}
    support = 0
    for table,key,strength in ((model["coarse"],coarse,40),(model["fine"],fine,60)):
        group = table.get(key)
        if group:
            n = group["n"]
            ready = (group["ready"]+strength*ready)/(n+strength)
            tiles = {tile:(group["waits"].get(tile,0)+strength*rate)/(n+strength) for tile,rate in tiles.items()}
            support = n
    return {"seat":seat, "training_distribution_tenpai_estimate":ready,
            "training_distribution_wait_rates":tiles, "local_training_support":support,
            "public_lock_blocks_ron":bool(obs["players"][seat].get("locked_with")),
            "deployment":"shadow-only", "human_calibrated":False,
            "scope":"弱机器人牌谱公共特征基线，不是对手实际待牌；结构听牌不等于能接炮；不参与自动风险排序"}


def metrics(model, records):
    total = len(records)
    if not total:
        return {"n":0}
    brier,constant = 0.,0.
    bins = [{"n":0,"predicted_sum":0.,"positive":0} for _ in range(5)]
    prior = model["global"]["ready"]/model["global"]["n"]
    for obs,target in records:
        p = predict(model,obs,target["seat"])["training_distribution_tenpai_estimate"]
        y = int(target["structural_tenpai"])
        brier += (p-y)**2
        constant += (prior-y)**2
        group = bins[min(4,int(p*5))]
        group["n"] += 1
        group["predicted_sum"] += p
        group["positive"] += y
    return {"n":total, "brier":brier/total, "constant_prior_brier":constant/total,
            "calibration_bins": [{"n":b["n"],"mean_prediction":b["predicted_sum"]/b["n"],
                                  "observed_frequency":b["positive"]/b["n"]} for b in bins if b["n"]]}


def fit(campaigns):
    records = {"train":[],"validation":[],"test":[]}
    families = {k:set() for k in records}
    seen = set()
    for campaign in campaigns:
        for labels in sorted(Path(campaign).glob("hand-*/labels-offline-only.jsonl")):
            observations = {}
            with (labels.parent/"decisions.jsonl").open() as stream:
                for line in stream:
                    row = json.loads(line)
                    observations[row["observation"]["observation_id"]] = row["observation"]
            with labels.open() as stream:
                for line in stream:
                    label = json.loads(line)
                    obs = observations[label["observation_id"]]
                    split,family = label["split"],label["wall_family"]
                    if any(family in families[s] for s in families if s != split):
                        raise ValueError("同牌墙泄漏到不同分区")
                    families[split].add(family)
                    for target in label["targets"]:
                        # The same target in a frozen response window is not
                        # three independent examples merely because seats differ.
                        key = (obs["observation_id"].rsplit(":",1)[0],target["seat"])
                        if key not in seen:
                            seen.add(key)
                            records[split].append((obs,target))
    if not records["train"]:
        raise ValueError("没有训练分区样本")
    model = {"version":VERSION,"global":_counter(),"coarse":{},"fine":{},
             "rules_versions":sorted({obs["rules_version"] for obs,_ in records["train"]}),
             "deployment":"shadow-only", "human_calibrated":False,
             "family_counts":{s:len(v) for s,v in families.items()}}
    for obs,target in records["train"]:
        coarse,fine = features(obs,target["seat"])
        for counter in (model["global"],model["coarse"].setdefault(coarse,_counter()),model["fine"].setdefault(fine,_counter())):
            _add(counter,target)
    model["evaluation"] = {s:metrics(model,records[s]) for s in ("validation","test")}
    model["data_warning"] = "仅弱机器人生成数据；留出牌墙少，不证明真人校准或棋力；禁止自动晋级为实战概率"
    return model


def load_model(path=DEFAULT_MODEL):
    path = Path(path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if data.get("version") != VERSION or not data.get("global",{}).get("n"):
        raise ValueError("无效对手模型")
    for group in [data["global"],*data["coarse"].values(),*data["fine"].values()]:
        if (type(group["n"]) is not int or group["n"] < 1 or type(group["ready"]) is not int
                or not 0 <= group["ready"] <= group["n"] or any(
                    type(n) is not int or not 0 <= n <= group["ready"] for n in group["waits"].values())):
            raise ValueError("对手模型计数无效")
    return data
