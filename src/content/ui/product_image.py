# -*- coding: utf-8 -*-
"""抽選・商品の画像（公式画像の参照表示と、公式画像が無いときの代わりの画像）。

TCG ハブ（tcg.html・tcg-lottery.html）と新UI（HOME の抽選カード・抽選ページの行）で共通に使う。

- 公式画像: verified_products.image_publishable が True の URL だけ。公式サイトへの直接参照（ホットリンク）で、
  保存・中継・再配信はしない。<img> には alt（商品名）・width/height・loading="lazy"・decoding="async"・
  referrerpolicy="strict-origin-when-cross-origin"（公式側から埋め込み元が見え、止められる状態にする）を付け、読み込みに失敗したら（onerror = IMG_ONERROR）代わりの画像に切り替える。
- 代わりの画像: 外部の画像を使わず、ページ内の SVG で作る。商品名の要点・型番（OP-19 など）・TCG の種類・
  商品の種類（BOX・デッキ等）を文字で入れるだけの中立なデザイン（公式のロゴ・キャラクターを真似しない）。
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

IMG_W, IMG_H = 320, 240                       # 縦横比 4:3（枠も同じ比で固定する）

# 画像の読み込みに失敗したとき、代わりの画像（[data-phb]）に切り替える。外部の値を埋め込まない定数
# （deploy-check が TCG のページで完全一致を検査する）
IMG_ONERROR = ("var p=this.parentNode;p.classList.add('ph');"
               "p.querySelectorAll('[data-phb]').forEach(function(e){e.hidden=false});this.remove()")

assert not any(c in IMG_ONERROR for c in '"<&')

IMG_CREDIT = ("商品画像: 公式サイトの画像を参照表示しています（©Pokémon ©Nintendo/Creatures Inc./GAME FREAK inc.／"
              "©尾田栄一郎／集英社・フジテレビ・東映アニメーション）")

TCG_BAND = {"POKEMON": "ポケモンカード", "ONE_PIECE": "ONE PIECE カード"}
# 中立な配色（TCG ごとに色味だけ変える。公式のロゴ・配色は真似しない）
_PALETTE = {"POKEMON": ("#eef3fa", "#2f5d9b"), "ONE_PIECE": ("#f6efe6", "#8a4b1f")}
_DEFAULT_PALETTE = ("#f1f2f4", "#4a5160")
_FG = "#1a1d23"
_FONT = "system-ui,-apple-system,'Hiragino Sans','Noto Sans JP',sans-serif"

TYPE_LABEL = {"BOOSTER_BOX": "パック・BOX", "ENHANCED_BOOSTER": "ブースター", "STARTER_DECK": "スタートデッキ",
              "CONSTRUCTED_DECK": "デッキセット", "SPECIAL_SET": "カードセット", "PREMIUM_COLLECTION": "コレクション"}
_NAME_KIND = (("BOX", "BOX"), ("ボックス", "BOX"), ("デッキ", "デッキ"), ("セット", "セット"), ("パック", "パック"),
              ("コレクション", "コレクション"), ("ブースター", "ブースター"))

_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,4}-\d{1,3}[A-Za-z]?)(?![A-Za-z0-9])")
_BRACKET_CODE_RE = re.compile(r"【\s*[A-Z]{1,4}-\d{1,3}[A-Za-z]?\s*】")
_QUOTE_RE = re.compile(r"[「『]([^「『」』]{2,})")
_PREFIX_RE = re.compile(r"^(?:【[^】]*】|ポケモンカードゲーム|ポケモンMEGA|MEGA|ONE\s*PIECE\s*カードゲーム|ワンピースカードゲーム|[・\s　])+")
_SERIES_RE = re.compile(r"^(?:プレミアムエクストラブースター|エクストラブースター|プレミアムブースター|ブースターパック|強化拡張パック|"
                        r"拡張パック|ハイクラスパック|スタートデッキ(?:EX)?|スペシャルカードセット)[\s　・]*")
_TAIL_RE = re.compile(r"(?:の(?:追加)?抽選販売について|抽選販売.*|※.*)$")


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def code_of(name: Any, code: Any = None) -> str:
    """型番（OP-19・ST-37 など）。台帳の値を優先し、無ければ商品名の中の型番。無ければ空（作らない）。"""
    c = str(code or "").strip()
    if c and _CODE_RE.fullmatch(c):
        return c
    m = _CODE_RE.search(str(name or ""))
    return m.group(1) if m else ""


def essence(name: Any) -> str:
    """商品名の要点（「」の中・シリーズ名や「ポケモンカードゲーム」等の前置きを外したもの）。外して空になれば元の名前。"""
    raw = str(name or "").strip()
    s = _BRACKET_CODE_RE.sub("", raw).strip()
    m = _QUOTE_RE.search(s)
    if m:
        s = m.group(1)
    s = _PREFIX_RE.sub("", s).strip()
    s = _SERIES_RE.sub("", s).strip()
    s = _TAIL_RE.sub("", s).strip(" 　・-「」『』")
    return s or raw


def kind_of(product_type: Any, name: Any = "", default: str = "商品") -> str:
    """商品の種類（台帳の product_type を優先。無ければ商品名の語から。分からなければ default）。"""
    lab = TYPE_LABEL.get(str(product_type or ""))
    if lab:
        return lab
    n = str(name or "")
    for word, lab in _NAME_KIND:
        if word in n:
            return lab
    return default


def _w(ch: str) -> float:
    return 1.0 if ord(ch) >= 0x2E80 else 0.6


def _wrap(text: str, max_em: float, lines: int) -> list[str]:
    """表示幅（全角 1・半角 0.6）で折り返す。入りきらない最後の行は「…」で切る。"""
    out, cur, width = [], "", 0.0
    for ch in text:
        if width + _w(ch) > max_em:
            cut = max(cur.rfind(" "), cur.rfind("　"))
            rest = ""
            if cut > 0 and ch not in " 　" and len(out) + 1 < lines:     # 英単語の途中で切らない（空白で折り返す）
                cur, rest = cur[:cut], cur[cut + 1:]
            out.append(cur)
            cur, width = rest, sum(_w(c) for c in rest)
            if len(out) == lines:
                break
        if not cur and ch in " 　":
            continue
        cur += ch
        width += _w(ch)
    else:
        if cur:
            out.append(cur)
        return out[:lines]
    last = out[-1]
    while last and sum(_w(c) for c in last) + 1.0 > max_em:
        last = last[:-1]
    out[-1] = last.rstrip() + "…"
    return out


def placeholder_svg(*, tcg: Any, name: Any, kind: str = "", code: str = "", band: str = "", style: str = "") -> str:
    """代わりの画像（ページ内の SVG）。文字はすべてエスケープする。外部の画像・フォントを読まない。"""
    tcg = str(tcg or "")
    bg, accent = _PALETTE.get(tcg, _DEFAULT_PALETTE)
    band = (band or TCG_BAND.get(tcg) or "抽選・予約")[:16]
    title = essence(name) or "商品名不明"
    rows = _wrap(title, 12.0, 2 if code else 3)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {IMG_W} {IMG_H}" width="{IMG_W}" height="{IMG_H}" '
        f'role="img" aria-label="{_e(str(name or title))}" focusable="false" font-family="{_FONT}" data-ph-svg'
        + (f' style="{style}"' if style else "") + '>',
        f'<rect width="{IMG_W}" height="{IMG_H}" fill="{bg}"/>',
        # 中立なモチーフ（重ねたカードの輪郭だけ）
        f'<g fill="none" stroke="{accent}" stroke-width="4" opacity=".18">'
        '<rect x="222" y="118" width="70" height="98" rx="8" transform="rotate(12 257 167)"/>'
        '<rect x="206" y="124" width="70" height="98" rx="8" transform="rotate(-6 241 173)"/></g>',
        f'<rect width="{IMG_W}" height="40" fill="{accent}"/>',
        f'<text x="16" y="27" font-size="17" font-weight="700" fill="#fff">{_e(band)}</text>',
    ]
    y = 88
    if code:
        parts.append(f'<text x="16" y="88" font-size="38" font-weight="800" fill="{accent}">{_e(code)}</text>')
        y = 128
    for i, line in enumerate(rows):
        parts.append(f'<text x="16" y="{y + i * 30}" font-size="24" font-weight="700" fill="{_FG}">{_e(line)}</text>')
    if kind:
        k = kind[:10]
        pw = int(28 + sum(_w(c) for c in k) * 16)
        parts.append(f'<rect x="16" y="194" width="{pw}" height="30" rx="15" fill="#fff" stroke="{accent}" stroke-width="2"/>'
                     f'<text x="30" y="215" font-size="16" font-weight="700" fill="{accent}">{_e(k)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def img_tag(src: str, alt: Any, style: str = "") -> str:
    """公式画像の <img>（公式サイトへの直接参照。失敗したら代わりの画像に切り替える）。"""
    st = f' style="{style}"' if style else ""
    return (f'<img src="{_e(src)}" alt="{_e(alt)}" width="{IMG_W}" height="{IMG_H}" loading="lazy" decoding="async" '
            f'referrerpolicy="strict-origin-when-cross-origin"{st} onerror="{IMG_ONERROR}">')          # 定数（" < & を含まない）をそのまま


def publishable(tcg: Any, url: Any) -> str:
    """公開ページに出してよい公式画像の URL（判定は verified_products.image_publishable が唯一の定義）。無ければ空。"""
    from src.tcg import verified_products as _vp
    return url if (isinstance(url, str) and _vp.image_publishable(tcg, url)) else ""


def figure(*, tcg: Any, name: Any, src: str = "", kind: str = "", code: str = "", band: str = "",
           cls: str = "nu-thumb", tag: str = "span", width: int | None = None) -> str:
    """画像の枠。公式画像があれば <img>（失敗時の代わりの画像を隠して添える）、無ければ代わりの画像。
    width を渡すと（新UI）、見た目をインラインの style で付ける（新UIの <style> は 1 つだけの決まりなので CSS を足さない）。
    渡さないと（TCG ハブ）、見た目は tcg_hub_page の CSS（.pimg）に任せる。"""
    box = inner = ""
    if width:
        box = f' style="{_BOX_STYLE}width:{int(width)}px"'
        inner = _INNER_STYLE
    svg = placeholder_svg(tcg=tcg, name=name, kind=kind, code=code, band=band, style=inner)
    if src:
        # 失敗時の代わりの画像は、隠した <span> の中（span は表示の規則を持たないので hidden がそのまま効く）
        return f'<{tag} class="{cls}"{box}>{img_tag(src, name, inner)}<span class="phs" data-phb hidden>{svg}</span></{tag}>'
    return f'<{tag} class="{cls} ph"{box}>{svg}</{tag}>'


# ── 抽選の VM に載せる画像の情報 ────────────────────────────────────

_REGISTRY = Path(__file__).resolve().parents[3] / "exports" / "tcg" / "pokemon_registry.json"


@lru_cache(maxsize=1)
def _index() -> dict:
    """(tcg, product_id) → 商品の行（公開済みの商品一覧 + 公式ページで確認した台帳）。読めなければ空。"""
    out: dict = {}
    try:
        rows = json.loads(_REGISTRY.read_text(encoding="utf-8")).get("products") or []
    except (OSError, ValueError, AttributeError):
        rows = []
    try:
        from src.tcg import verified_products as _vp
        rows = list(rows) + _vp.load()
    except Exception:  # noqa: BLE001 — 台帳が読めなくても代わりの画像は出す
        pass
    for r in rows:
        if isinstance(r, dict) and r.get("tcg") and r.get("product_id"):
            out.setdefault((str(r["tcg"]), str(r["product_id"])), r)
    return out


def pic_for_event(ev: dict, *, bound: bool) -> dict:
    """抽選・発売予定の 1 件 → {"u": 公式画像の URL（出せるときだけ）, "n": 名前, "pt": 種類, "c": 型番}。
    公式画像は、商品に紐付いた（bound）商品一覧の行の画像だけ。紐付いていなければ代わりの画像の材料だけを返す。"""
    ev = ev if isinstance(ev, dict) else {}
    tcg, pid = str(ev.get("tcg") or ""), str(ev.get("product_id") or "")
    row = _index().get((tcg, pid)) if (bound and tcg and pid) else None
    name = str((row or {}).get("name") or ev.get("product_name") or "")
    url = (row or {}).get("official_image_url") or (ev.get("official_image_url") if bound else None)   # 公式の発売予定は自身の画像
    return {"u": publishable(tcg, url) if (row or bound) else "",
            "n": name, "pt": str((row or {}).get("product_type") or (ev.get("product_type") if bound else "") or ""),
            "c": code_of(name, (row or {}).get("product_code") or ev.get("product_code"))}


def vm_figure(vm: dict, width: int = 96, cls: str = "nu-thumb") -> str:
    """新UIの抽選の VM → 画像の枠（TCG は vm["pic"]、それ以外は商品名とブランドから代わりの画像）。"""
    pic = vm.get("pic") if isinstance(vm.get("pic"), dict) else {}
    tcg = str(vm.get("cat") or "")
    name = pic.get("n") or vm.get("t") or ""
    band = TCG_BAND.get(tcg) or str(vm.get("sub") or "").split("・")[0]
    kind = kind_of(pic.get("pt"), name, default={"preorder": "予約", "release": "発売予定"}.get(str(vm.get("k") or ""), "抽選"))
    src = publishable(tcg, pic.get("u")) if pic.get("u") else ""
    return figure(tcg=tcg, name=name, src=src, kind=kind, code=code_of(name, pic.get("c")), band=band, cls=cls, width=width)


# 新UIの画像の枠の見た目（インラインの style。新UIの CSS（styles.py）には足さない。縦横比 4:3 を固定）
_BOX_STYLE = ("flex:none;display:block;aspect-ratio:4/3;overflow:hidden;border-radius:6px;background:#fff;"
              "border:1px solid var(--color-border,#e2e5ea);")
_INNER_STYLE = "display:block;width:100%;height:100%;object-fit:contain"
CREDIT_STYLE = "margin:8px 0 0;font-size:var(--font-xs,12px);color:var(--color-subtle,#5b6270)"
