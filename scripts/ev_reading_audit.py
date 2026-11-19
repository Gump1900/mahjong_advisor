"""Audit ordered-history influence on frozen public observations, not playing strength.

Usage: .venv/bin/python scripts/ev_reading_audit.py 2
Each move is compared with the same strategy given only current rivers, then
only the full-history move is executed. The comparison never sees referee hands.
"""
import json
from copy import deepcopy
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.decision.ev_bot import EVBot
from src.simulation.engine import Table
from src.simulation.runner import play


def audit(games=2):
    stats = {'games': 0, 'decisions': 0, 'history_changes': 0,
             'examples': [], 'max_decision_ms': 0}

    class AuditBot(EVBot):
        def choose(self, observation):
            started = time.monotonic()
            choice = super().choose(observation)
            stats['max_decision_ms'] = max(stats['max_decision_ms'], round((time.monotonic()-started)*1000, 2))
            river_only = deepcopy(observation)
            river_only['events'] = []
            alternative = super().choose(river_only)
            stats['decisions'] += 1
            if choice.action_id != alternative.action_id:
                stats['history_changes'] += 1
                if len(stats['examples']) < 5:
                    actions = {a['id']: {'kind': a['kind'], 'tiles': a['tiles']}
                               for a in observation['legal_actions']}
                    stats['examples'].append({'seed': current_seed,
                        'step': observation['observation_id'].split(':')[1],
                        'with_history': actions[choice.action_id],
                        'river_only': actions[alternative.action_id]})
            return choice

    for current_seed in range(8200, 8200+games):
        table = Table(seed=current_seed)
        play(table, {seat: AuditBot('均衡', samples=32, seed=seat) for seat in range(4)})
        table.assert_consistent()
        stats['games'] += 1
    stats['scope'] = '同局同观察的有序历史/仅牌河消融；不是新旧策略胜率对比，不能证明棋力提升'
    return stats


if __name__ == '__main__':
    result = audit(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
    output = Path('runs/dynamic-reading-evaluation.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
