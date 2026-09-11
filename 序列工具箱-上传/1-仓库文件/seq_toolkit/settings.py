"""用户配置读写。文件损坏或以任何方式不可读时必须回退到默认值，绝不抛异常。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .format_detect import DEFAULT_FASTA_SUFFIXES, DEFAULT_GENBANK_SUFFIXES

_APP_DIR = "seq_toolkit"
_FILE_NAME = "settings.json"

# 显式类型表。本模块启用了 from __future__ import annotations，
# 因此 dataclasses.fields(Settings)[i].type 是字符串（'str'/'int'/'tuple'）而非类型对象，
# 用它做 target_type is tuple 之类的比较会永远为假——所有字段都会静默退回默认值，
# 且不报错，表现为"配置文件怎么改都不生效"。故类型只从这张表取。
_SCHEMA = {
    "email": str,
    "api_key": str,
    "proxy": str,
    "output_dir": str,
    "wrap": int,
    "force_redownload": bool,
    "fasta_suffixes": tuple,
    "genbank_suffixes": tuple,
}


@dataclass
class Settings:
    email: str = ""
    api_key: str = ""
    proxy: str = ""
    output_dir: str = ""
    wrap: int = 0
    force_redownload: bool = False
    fasta_suffixes: tuple[str, ...] = field(default=DEFAULT_FASTA_SUFFIXES)
    genbank_suffixes: tuple[str, ...] = field(default=DEFAULT_GENBANK_SUFFIXES)


def _base_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _APP_DIR)


def settings_path() -> str:
    return os.path.join(_base_dir(), _FILE_NAME)


def _coerce(raw: dict, target_type, default, key: str):
    """只接受类型匹配的值，否则退回默认值——配置文件是外部输入，必须防御。"""
    value = raw.get(key, default)
    if target_type is tuple:
        if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
            return tuple(value)
        return default
    if target_type is bool:
        return value if isinstance(value, bool) else default
    if target_type is int:
        return value if isinstance(value, int) and not isinstance(value, bool) else default
    return value if isinstance(value, target_type) else default


def load_settings(path: str | None = None) -> Settings:
    target = path or settings_path()
    defaults = Settings()
    try:
        # 读入用 utf-8-sig：兼容"带 BOM 的 UTF-8"——Windows 记事本存盘默认就是这种。
        # 用普通 utf-8 会让整个文件被判为非法 JSON，8 个字段全部静默回默认值，
        # 用户观感是"配置文件怎么改都不生效"。此举与全局约束"读入用 utf-8-sig"一致。
        with open(target, "rt", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            return defaults
    except (OSError, ValueError, RecursionError, MemoryError):
        # RecursionError 与 MemoryError 必须一并捕获：畸形或超大的配置文件（例如
        # 深度极大的嵌套数组）抛的正是这两类，而它们都不是 ValueError/OSError 的子类。
        # 本函数对外的契约是"任何配置问题都不得抛异常"，否则调用方（GUI 启动、
        # 下载流程）会直接崩掉，而不是退回默认配置。
        return defaults

    values = {}
    for name, target_type in _SCHEMA.items():
        values[name] = _coerce(raw, target_type, getattr(defaults, name), name)
    return Settings(**values)


def save_settings(settings: Settings, path: str | None = None) -> str:
    target = path or settings_path()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = asdict(settings)
    with open(target, "wt", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return target
