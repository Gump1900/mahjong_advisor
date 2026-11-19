"""Offline public-feature baseline; never calls an LLM or reads API keys."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.players.opponent_model import fit, DEFAULT_MODEL
from src.simulation.experiment import private_json


def main(argv=None):
    p = argparse.ArgumentParser(description="训练公共特征听牌基线（影子模式，非真人校准）")
    p.add_argument("campaigns",nargs="+",type=Path)
    p.add_argument("--output",type=Path,default=DEFAULT_MODEL)
    args = p.parse_args(argv)
    model = fit(args.campaigns)
    private_json(args.output,model)
    print(json.dumps({"output":str(args.output),"families":model["family_counts"],"evaluation":model["evaluation"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
