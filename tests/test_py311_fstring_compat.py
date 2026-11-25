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
    stack: list[tuple[str, int]] = []                  # (外側の引用符, 開始時の波括弧の深さ)
    bad: list[int] = []
    depth = 0

    def _clash(q: str, line: int) -> None:
        # 内側の文字列（通常の文字列も入れ子の f 文字列も）が、外側のどの f 文字列の式の中でも、その外側と同じ 1 文字の引用符なら違反
        for oq, d0 in stack:
            if depth > d0 and len(oq) == 1 and q[:1] == oq:
                bad.append(line)

    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == start:
            q = tok.string.lstrip("rRbBuUfF")
            _clash(q, tok.start[0])
            stack.append((q, depth))
        elif tok.type == end:
            if stack:
                stack.pop()
        elif tok.type == tokenize.OP and tok.string == "{" and stack:
            depth += 1
        elif tok.type == tokenize.OP and tok.string == "}" and stack:
            depth -= 1
        elif tok.type == tokenize.STRING and stack:
            _clash(tok.string.lstrip("rRbBuUfF"), tok.start[0])
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


def test_detector_catches_nested_fstring_with_inner_string_matching_outer_quote():
    """内側の f 文字列（別の引用符）の式の中で、さらに外側の f 文字列と同じ引用符を使う形（tcg_hub_page の _rb_card で実際に起きた）。"""
    if sys.version_info < (3, 12):
        pytest.skip("3.12 以降でのみ")
    bad = "x = f'{(f\"a {d.get('k')} b\") if d else \"\"}'\n"
    assert _reused_quotes(bad) == [1]
    ok = "k = d.get('k')\nx = f'{(f\"a {k} b\") if d else \"\"}'\n"
    assert _reused_quotes(ok) == []
    assert _reused_quotes("x = f'{f\"{'a'}\"}'\n") == [1]
