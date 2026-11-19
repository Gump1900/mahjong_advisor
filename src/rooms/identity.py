"""访客身份（规划 §9.4）：临时访客标识 + 会话凭证。

浏览器会话与逻辑玩家身份分开：token 只是凭证，昵称不作为控制座位的依据。
"""
import secrets
from typing import Dict, Tuple


class VisitorRegistry:
    def __init__(self):
        self._visitors: Dict[str, dict] = {}
        self._tokens: Dict[str, str] = {}

    def create(self, nickname: str = "") -> Tuple[str, str]:
        vid = "v" + secrets.token_hex(8)
        nickname = nickname or f"访客{len(self._visitors) + 1:03d}"
        self._visitors[vid] = {"id": vid, "nickname": nickname}
        token = secrets.token_urlsafe(24)
        self._tokens[token] = vid
        return vid, token

    def resolve(self, token: str) -> dict:
        vid = self._tokens[token]
        return dict(self._visitors[vid])

    def nickname(self, vid: str) -> str:
        return self._visitors[vid]["nickname"]

    def to_dict(self) -> dict:
        return {"visitors": dict(self._visitors), "tokens": dict(self._tokens)}

    @classmethod
    def from_dict(cls, data: dict) -> "VisitorRegistry":
        reg = cls()
        reg._visitors = {k: dict(v) for k, v in data.get("visitors", {}).items()}
        reg._tokens = dict(data.get("tokens", {}))
        return reg
