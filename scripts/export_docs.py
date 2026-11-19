"""Export canonical Markdown to readable HTML and optional runtime knowledge.

Install the exporter dependency: python -m pip install 'Markdown>=3.7,<4'
No source Markdown is modified; artifacts/ is disposable and ignored by Git.
"""
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import os
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.players.knowledge import export_knowledge


def export(root=ROOT):
    try:
        import markdown
    except ImportError:
        raise SystemExit("导出HTML需安装：python -m pip install 'Markdown>=3.7,<4'") from None
    root = Path(root)
    output = root/'artifacts/docs'
    output.mkdir(parents=True, exist_ok=True)
    sources = [root/'README.md', *sorted((root/'docs').glob('*.md')), root/'prototype/design.md']
    targets = {p.resolve(): output/('index.html' if p == root/'README.md' else 'prototype.html' if p.parent.name == 'prototype' else p.stem+'.html') for p in sources}

    class Links(HTMLParser):
        def __init__(self, source):
            super().__init__(convert_charrefs=False)
            self.source, self.parts = source, []
        def handle_starttag(self, tag, attrs):
            rewritten = []
            for key, value in attrs:
                if key in ('href', 'src') and value:
                    url = urlsplit(value)
                    if url.path and not url.scheme and not url.netloc:
                        source_path = (self.source.parent/unquote(url.path)).resolve()
                        dest = targets.get(source_path, source_path)
                        value = os.path.relpath(dest, output)+('?' + url.query if url.query else '')+('#'+url.fragment if url.fragment else '')
                rewritten.append(' '+key if value is None else f' {key}="{escape(value, quote=True)}"')
            self.parts.append('<'+tag+''.join(rewritten)+'>')
        def handle_endtag(self, tag): self.parts.append('</'+tag+'>')
        def handle_data(self, data): self.parts.append(data)
        def handle_entityref(self, name): self.parts.append('&'+name+';')
        def handle_charref(self, name): self.parts.append('&#'+name+';')

    nav = ' · '.join(f'<a href="{p.name}">{escape(s.stem)}</a>' for s,p in targets.items())
    style = 'body{max-width:1000px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui;color:#243d34;background:#f7f7f1}nav{font-size:13px;line-height:2.2}a{color:#21684e}pre{padding:20px;background:#e9eee6;overflow:auto;line-height:1.5}code{font-size:13px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px 12px;border:1px solid #cbd4c7;text-align:left;vertical-align:top}h1,h2,h3{line-height:1.4}h2{margin-top:36px}blockquote{border-left:3px solid #93a98c;padding-left:16px;color:#60715c}'
    for source, target in targets.items():
        body = markdown.markdown(source.read_text(encoding='utf-8'), extensions=['extra','toc','sane_lists'])
        links = Links(source); links.feed(body)
        target.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(source.stem)+'</title><style>'+style+'</style><nav>'+nav+'</nav><main>'+''.join(links.parts)+'</main></html>', encoding='utf-8')
    knowledge = export_knowledge(root)
    return len(targets), knowledge


if __name__ == '__main__':
    count, knowledge = export()
    print(f'已生成{count}份HTML至artifacts/docs/；运行时知识：{knowledge.relative_to(ROOT)}')
