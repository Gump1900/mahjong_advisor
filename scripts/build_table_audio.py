"""Build local female speech clips on macOS; no API or remote assets used.

Requires the installed Tingting voice, `say`, and ffmpeg. Generated clips are
for this local table; no QQ/Tencent recordings or music are copied.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

OUTPUT = Path(__file__).resolve().parents[1] / "src/simulation/webapp/audio"
NUMBERS = "一二三四五六七八九"


def phrases():
    result = {f"{suit}{n}": NUMBERS[n-1]+label
              for suit, label in (("man", "万"), ("pin", "饼"), ("sou", "条")) for n in range(1, 10)}
    result.update(south="南风", west="西风", north="北风", chi="吃", peng="碰", kong="杠",
                  win="胡了", flower="换花", draw_round="流局", lock="三口互锁，只能自摸", start="开局")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="Tingting")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not shutil.which("say") or not shutil.which("ffmpeg"):
        parser.error("需要macOS say及ffmpeg，不会自动下载安装")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mahjong-voice-") as temp:
        for name, phrase in phrases().items():
            target = OUTPUT / f"{name}.m4a"
            if target.exists() and not args.force:
                continue
            source = Path(temp) / f"{name}.aiff"
            subprocess.run(["say", "-v", args.voice, "-r", "220", "-o", str(source), phrase], check=True)
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source),
                            "-map", "0:a:0",
                            "-af", "silenceremove=start_periods=1:start_threshold=-45dB,loudnorm=I=-18:TP=-2:LRA=7",
                            "-c:a", "aac", "-b:a", "64k", "-ar", "24000", str(target)], check=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "json", str(target)], check=True, capture_output=True, text=True)
            if float(json.loads(probe.stdout).get("format", {}).get("duration", 0)) <= 0:
                raise RuntimeError("语音文件为空，请确认macOS语音服务可在当前权限下运行")
    print(f"已生成{len(phrases())}段本地女声：{OUTPUT}")


if __name__ == "__main__":
    main()
