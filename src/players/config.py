"""Private local credentials, resolved relative to the repository, not cwd.

Never include the loaded configuration in prompts, observations or replay data.
"""
from pathlib import Path
import tomllib

LOCAL_CONFIG = Path(__file__).resolve().parents[2] / "config" / "local.toml"


def load_local_config():
    try:
        with LOCAL_CONFIG.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        # TOML diagnostics can include the line containing a credential.
        raise ValueError("无法读取config/local.toml，请检查文件权限和TOML格式；配置内容未输出") from None
    for provider in ("deepseek", "anthropic"):
        section = data.get(provider, {})
        if not isinstance(section, dict) or any(
            not isinstance(section.get(field, ""), str) for field in ("api_key", "model")
        ):
            raise ValueError("config/local.toml的供应商配置须为表，api_key和model须为字符串")
    return data
