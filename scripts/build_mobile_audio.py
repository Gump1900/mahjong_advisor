"""Package existing local table voice and synthesize mobile settlement/effect clips.

Run from repository root: python3 -m scripts.build_mobile_audio
Uses installed macOS Tingting and ffmpeg, never a network speech API.
"""
import json
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import wave

from scripts.build_table_audio import OUTPUT as TABLE_AUDIO, phrases

OUTPUT = Path(__file__).resolve().parents[1] / 'clients/miniprogram/assets/audio'
EXTRA = {**{f'num{i}': s for i,s in enumerate('零一二三四五六七八九')},
         'num10':'十','num100':'百','num1000':'千',
         'settle_win':'本局你赢了','settle_loss':'本局你输了','settle_zero':'本局不输不赢',
         'points':'分','settlement':'本局结算已更新'}


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mahjong-mobile-audio-') as folder:
        for key, text in {**phrases(), **EXTRA}.items():
            target=OUTPUT/f'{key}.m4a'
            if target.exists(): continue
            old=TABLE_AUDIO/f'{key}.m4a'
            if old.exists():
                shutil.copyfile(old,target)
                continue
            source=Path(folder)/f'{key}.aiff'
            subprocess.run(['say','-v','Tingting','-r','220','-o',str(source),text],check=True)
            subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(source),'-af',
                            'silenceremove=start_periods=1:start_threshold=-45dB,loudnorm=I=-18:TP=-2:LRA=7',
                            '-c:a','aac','-b:a','64k','-ar','24000',str(target)],check=True)
        for key, freq in [('tile_draw',550),('tile_discard',260)]:
            target=OUTPUT/f'{key}.m4a'
            if target.exists(): continue
            source=Path(folder)/f'{key}.wav'
            rng=random.Random(freq)
            with wave.open(str(source),'wb') as stream:
                stream.setparams((1,2,24000,0,'NONE','not compressed'))
                samples=[]
                for i in range(3600):
                    t=i/24000
                    envelope=min(1,t/.004)*math.exp(-t*34)
                    v=(.35*math.sin(2*math.pi*freq*t)+.12*rng.uniform(-1,1))*envelope
                    samples.append(struct.pack('<h',int(v*32767)))
                stream.writeframes(b''.join(samples))
            subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(source),
                            '-c:a','aac','-b:a','64k',str(target)],check=True)
    manifest={'source':'Existing table Tingting voice + local offline speech and original procedural tile effects',
              'clips':sorted(p.stem for p in OUTPUT.glob('*.m4a'))}
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(f'本地音频已准备：{len(manifest["clips"])}段，{OUTPUT}')


if __name__=='__main__': main()
