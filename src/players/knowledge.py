"""Build optional model context from canonical docs; no second editable rules copy."""
from pathlib import Path
import os
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def _section(text, title):
    match = re.search(r'^## '+re.escape(title)+r'\s*\n', text, re.M)
    if not match:
        raise ValueError(f'知识源缺少章节：{title}')
    tail = text[match.end():]
    end = re.search(r'^## ', tail, re.M)
    return tail[:end.start() if end else len(tail)].strip()


def load_knowledge(root=ROOT):
    """Read current sources on demand, so old generated artifacts cannot override rules."""
    root = Path(root)
    rules = (root/'docs/rules.md').read_text(encoding='utf-8')
    strategy = (root/'docs/strategy.md').read_text(encoding='utf-8')
    sources = [(rules, '玩法范围', '2. 这套玩法的核心'),
               (rules, '牌与胡牌结构', '3. 牌与胡牌结构'),
               (rules, '留花与换牌', '4. 留花与换牌'),
               (rules, '响应、暗杠与过圈', '5. 响应、暗杠与过圈'),
               (rules, '胡牌资格与结算', '6. 胡牌资格、计分和结算'),
               (rules, '牌型加分', '7. 牌型加分'),
               (strategy, '取舍原则', '8. 策略理解：给机会定价，不套口诀'),
               (strategy, '信息边界', '9. 信息边界与暗杠推断'),
               (strategy, '基础牌理与复盘核对', '10.1 基础牌理与复盘核对：先比较，后批评')]
    return '# 太湖麻将运行时知识（由主文档生成，请勿手改）\n\n'+ '\n\n'.join(
        '## '+heading+'\n\n'+_section(source, title) for source, title, heading in sources)+'\n'


def export_knowledge(root=ROOT):
    root = Path(root)
    content = load_knowledge(root)
    output = root/'artifacts/context/knowledge.md'
    if output.exists() and output.read_text(encoding='utf-8') == content:
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return output
