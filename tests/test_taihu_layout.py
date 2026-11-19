"""Contract for the approved four-zone desktop design (browser QA separately)."""
from pathlib import Path

ASSETS = Path(__file__).parents[1] / "src/simulation/webapp"


def test_taihu_brand_and_last_layout_stylesheet():
    html = (ASSETS / "index.html").read_text()
    assert "太湖麻将" in html and "乡里麻将" not in html
    assert html.index('/board-layout.css') > html.index('/table.css')
    assert '/desktop.css' not in html and '/square.css' not in html


def test_capacity_and_equal_public_slot_dimensions():
    css = (ASSETS / "board-layout.css").read_text()
    assert "repeat(6,var(--river-w))" in css
    assert "flex-wrap:nowrap" in css  # Melds stay intact.
    assert ".seat-surface" in css and ".table .exposed" in css
    assert ".table .table-tile > img" in css
    assert "scale(" not in css and "zoom:" not in css
    assert "body.details-open main > .info-sidebar" in css


def test_information_control_does_not_hide_history():
    js = (ASSETS / "table.js").read_text()
    assert 'classList.toggle("details-open")' in js
