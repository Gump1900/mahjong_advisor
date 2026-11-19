"""Canonical document changes must invalidate optional runtime context, including stale exports."""
from pathlib import Path
import shutil

from src.players.knowledge import load_knowledge, export_knowledge
from src.players.table_decision import compact_rules


def test_runtime_context_ignores_stale_export_and_reads_current_rule_source(tmp_path):
    (tmp_path/'docs').mkdir()
    for name in ('rules.md','strategy.md'):
        shutil.copyfile(Path('docs')/name,tmp_path/'docs'/name)
    output=export_knowledge(tmp_path)
    old=output.read_text()
    output.write_text('过期上下文不得覆盖确认规则')
    assert load_knowledge(tmp_path)==old
    rules=tmp_path/'docs/rules.md'
    rules.write_text(rules.read_text().replace('庄家起手14张','测试修订：庄家起手14张'))
    assert '测试修订' in load_knowledge(tmp_path)
    assert '测试修订' in export_knowledge(tmp_path).read_text()


def test_compact_context_keeps_rules_and_experience_appendix_without_project_history():
    knowledge=load_knowledge()
    appendix='\n太湖打法参考（软经验，不是新规则）：\n本次选择的T01'
    compact=compact_rules(knowledge+appendix)
    assert '三豪华七对' in compact and '60' in compact
    assert '吃碰取得回合' in compact
    assert '689筒' in compact
    assert compact.endswith(appendix)
    assert '## 当前状态' not in compact and '已生成9份' not in compact
