"""成果物（exports/ の JSON など）を一時ファイルに書いてから置き換える。

書き込みの途中で失敗しても、前回のファイルが半端な内容で壊れない（置き換えは同じディレクトリ内の os.replace）。
生成の途中で失敗した場合は前回のファイルが残る。古いファイルを最新として扱わないことは、読む側
（generated_at を出す・route_id を今のルートと照合する）で行う。時刻を書き換えて新しく見せることはしない。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # 権限は置き換え前のファイルを引き継ぐ（無ければ通常のファイルと同じ。mkstemp の 0600 のままにしない）
        try:
            mode = p.stat().st_mode & 0o777
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path | str, data, **dump_kw) -> None:
    """JSON にできることを確かめてから（dumps が通ってから）置き換える。"""
    dump_kw.setdefault("ensure_ascii", False)
    dump_kw.setdefault("indent", 2)
    write_text_atomic(path, json.dumps(data, **dump_kw))
