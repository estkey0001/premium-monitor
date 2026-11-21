"""CI は Python 3.11。f 文字列の中で外側と同じ引用符を使う書き方（3.12 以降のみ有効）を src / scripts に入れない。
入れると CI で SyntaxError になり、tcg.html のように「前回のページが残る」形で静かに壊れる。"""
import io
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _reused_quotes(src: str) -> list[int]:
    """3.12 の tokenize は f 文字列を FSTRING_START/MIDDLE/END に分ける。波括弧の中に外側と同じ引用符の文字列があれば違反。"""
    start = getattr(tokenize, "FSTRING_START", None)
    end = getattr(tokenize, "FSTRING_END", None)
    if start is None or end is None:
        return []
    stack: list[tuple[str, int]] = []                  # (外側の引用符, 波括弧の深さ)
    bad: list[int] = []
    depth = 0
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == start:
            q = tok.string.lstrip("rRbBuUfF")
            stack.append((q, depth))
        elif tok.type == end:
            if stack:
                stack.pop()
        elif tok.type == tokenize.OP and tok.string == "{" and stack:
            depth += 1
        elif tok.type == tokenize.OP and tok.string == "}" and stack:
            depth -= 1
        elif tok.type == tokenize.STRING and stack and depth > stack[-1][1]:
            inner = tok.string.lstrip("rRbBuUfF")
            if inner[:1] == stack[-1][0][:1] and len(stack[-1][0]) == 1:
                bad.append(tok.start[0])
    return sorted(set(bad))


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.12 の tokenize でだけ検査できる")
def test_no_py312_only_fstring_quotes():
    found = {}
    for d in ("src", "scripts"):
        for f in (ROOT / d).rglob("*.py"):
            try:
                bad = _reused_quotes(f.read_text(encoding="utf-8"))
            except (tokenize.TokenError, SyntaxError):
                continue
            if bad:
                found[str(f.relative_to(ROOT))] = bad
    assert not found, f"f 文字列の中で同じ引用符を使っている（Python 3.11 で SyntaxError）: {found}"


def test_detector_catches_the_known_bad_pattern():
    if sys.version_info < (3, 12):
        pytest.skip("3.12 以降でのみ")
    assert _reused_quotes("x = f'{'a' if y else ''}'\n") == [1]
    assert _reused_quotes("x = f'{\"a\" if y else \"\"}'\n") == []
