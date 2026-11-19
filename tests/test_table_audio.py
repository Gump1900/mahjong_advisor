"""Audio is driven by public presentation frames, never hidden tile names."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.build_table_audio import phrases
from src.simulation.web import ASSETS


def test_female_clip_inventory_and_real_audio_streams():
    assert len(phrases()) == 38
    for name in phrases():
        path = ASSETS / "audio" / f"{name}.m4a"
        assert path.is_file() and path.stat().st_size > 1000
    if not shutil.which("ffprobe"):
        return
    for name in phrases():
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "json", str(ASSETS / "audio" / f"{name}.m4a")], capture_output=True, text=True, check=True)
        assert 0 < float(json.loads(result.stdout)["format"]["duration"]) < 6


def test_public_event_mapping_never_speaks_unknown_tiles():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
function el(){return {append(){},setAttribute(){},pause(){}};}
const ctx=vm.createContext({console,localStorage:{getItem:()=>null},
 document:{createElement:el,querySelector:el,body:el(),addEventListener(){}}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const a=ctx.TableAudio;
assert.equal(a.isEnabled(),false); // Never autoplay before a user gesture.
assert.equal(a.isConfiguredOn(),true); // Enabled by default; any first interaction unlocks audio.
assert.equal(a.clipForEvent({kind:'discard',tile:'6万'}),'man6');
assert.equal(a.clipForEvent({kind:'discard',tile:'9饼'}),'pin9');
assert.equal(a.clipForEvent({kind:'discard',tile:'北风'}),'north');
assert.equal(a.clipForEvent({kind:'an_gang',tile:'2条',hidden:true}),'kong');
assert.equal(a.clipForEvent({kind:'draw',tile:'2条',hidden:true}),null);
assert.equal(a.clipForEvent({kind:'draw',tile:'2条'}),null);
assert.equal(a.clipForEvent({kind:'flower_batch',tiles:['中','发']}),'flower');
assert.equal(a.clipForEvent({kind:'three_calls_lock'}),'lock');
assert.equal(a.clipForEvent({kind:'end',result:{method:'draw'}}),'draw_round');
assert.equal(a.clipForEvent({kind:'end',result:{method:'zimo'}}),null);
'''
    result = subprocess.run([node, "-e", script, str(ASSETS / "audio.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_audio_is_local_and_synchronized_not_replayed_on_refresh():
    js = (ASSETS / "table.js").read_text()
    audio = (ASSETS / "audio.js").read_text()
    html = (ASSETS / "index.html").read_text()
    assert html.index('/audio.js') < html.index('/table.js')
    assert "TableAudio?.present(state.presentation)" in js
    assert "TableAudio?.pause(paused)" in js
    assert "speechSynthesis" not in audio and "api.deepseek" not in audio
    assert "visibilitychange" in audio and "stopVoice()" in audio
    assert "master:true" in audio
    assert 'addEventListener("pointerdown",activate' in audio
    assert 'addEventListener("keydown",activate' in audio
    assert "prefs.master=false;save()" in audio
