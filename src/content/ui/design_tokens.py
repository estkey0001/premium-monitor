"""新UIのデザイントークン（internal/uiux/DESIGN_SYSTEM.md の実装）。

新UI（#new-ui-root 配下）だけで使う。旧UIの色・文字・余白には一切触れない。
値を増やすときはこのファイルだけを変更し、部品側に直書きしない。
"""

from __future__ import annotations

# 意味のある色（状態を表すときだけ使う）
# fg = 文字色、bg = 背景色、bd = 枠線。文字と背景のコントラストは 4.5:1 以上。
TONES: dict[str, dict[str, str]] = {
    "danger": {"fg": "#b91c1c", "bg": "#fef2f2", "bd": "#fecaca"},   # 赤: 急ぎ・締切間近
    "warning": {"fg": "#b45309", "bg": "#fffbeb", "bd": "#fde68a"},  # 橙: 注意・まもなく開始
    "success": {"fg": "#047857", "bg": "#ecfdf5", "bd": "#a7f3d0"},  # 緑: 応募できる・買える
    "info": {"fg": "#1d4ed8", "bg": "#eff6ff", "bd": "#bfdbfe"},     # 青: 情報
    "neutral": {"fg": "#475569", "bg": "#f1f5f9", "bd": "#e2e8f0"},  # 灰: 終了・動きなし
}

# 基本の色
BASE_COLORS: dict[str, str] = {
    # ページの背景は全ページ純白に統一（2026-11-27。TCG の --tc-bg と同じ）。面の区切りは surface-2 と枠線で付ける
    "bg": "#ffffff",
    "surface": "#ffffff",
    "surface-2": "#f1f5f9",
    "border": "#e2e8f0",
    # 操作部品（入力・チップ・ボタン）の枠。白の上で 3.75:1（WCAG 1.4.11 の 3:1）
    "border-strong": "#778599",
    "text": "#0f172a",
    "muted": "#475569",
    # 補助文字。neutral-bg（#f1f5f9）の上でも 5.4:1（旧 #64748b は 4.34:1 で AA 未達）
    "subtle": "#586579",
    # アクセントは青系1色（UI Phase 1）。白背景との文字コントラスト 5.2:1
    "primary": "#2563eb",
    "primary-contrast": "#ffffff",
    "primary-soft": "#eff6ff",
    "focus": "#1d4ed8",
}

# ダーク（prefers-color-scheme:dark）の値。キーはライトと同じ。文字と背景は 4.5:1 以上（muted 8.07 / subtle 6.06 など）
DARK_TONES: dict[str, dict[str, str]] = {
    "danger": {"fg": "#fca5a5", "bg": "#2d1517", "bd": "#6b2a2d"},
    "warning": {"fg": "#fcd34d", "bg": "#2b2110", "bd": "#6b5420"},
    "success": {"fg": "#4ade80", "bg": "#0f2a1c", "bd": "#1f5c3a"},
    "info": {"fg": "#93c5fd", "bg": "#10243d", "bd": "#2a4f80"},
    "neutral": {"fg": "#a3adbd", "bg": "#1e2736", "bd": "#2a3345"},
}
DARK_BASE_COLORS: dict[str, str] = {
    "bg": "#0f1520",
    "surface": "#171e2b",
    "surface-2": "#1e2736",
    "border": "#2a3345",
    "border-strong": "#667389",
    "text": "#e6e9ef",
    "muted": "#a3adbd",
    "subtle": "#8b95a7",
    "primary": "#7fb0ff",
    "primary-contrast": "#0f1520",
    "primary-soft": "#10243d",
    "focus": "#93c5fd",
}

# フォントスタック（HOME・旧ページ共通。ここだけが正本）
FONT_STACK = "-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif"

# 文字サイズ（px）。この6種類以外は使わない
FONT_SIZES: dict[str, int] = {"xs": 12, "sm": 14, "md": 16, "lg": 20, "xl": 24, "xxl": 32}

# 余白（px）
SPACING: dict[str, int] = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 24, "6": 32, "7": 48}

# 角丸（px）。pill はチップ専用
RADIUS: dict[str, int] = {"sm": 8, "md": 12, "lg": 16}

# 影は1種類だけ
SHADOW = "0 1px 2px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.08)"

# タップ対象の最小サイズ（px）
TAP_MIN = 44

# ブレークポイント（px）。モバイル < 640 ≦ タブレット < 900 ≦ デスクトップ（1024 以上でジャンルを6列）
BP_MOBILE = 640
BP_DESKTOP = 900
BP_WIDE = 1024
# 上部ナビに切り替える幅（これ未満はボトムナビ。640〜767px では上部ナビの5項目がヘッダーに収まらない）
BP_TOPNAV = 768
# 利益商品の比較テーブルを出す幅（未満はカード。列が多いので広い画面だけ）
BP_OPP_TABLE = 1200

# 中身の最大幅（中央寄せ）
MAX_WIDTH = 1240

# ボトムナビの高さ（px）
BOTTOM_NAV_HEIGHT = 56


def css_variables() -> str:
    """#new-ui-root に定義する CSS カスタムプロパティを返す。"""
    lines: list[str] = []
    for name, value in BASE_COLORS.items():
        lines.append(f"--color-{name}:{value};")
    for tone, vals in TONES.items():
        for part, value in vals.items():
            lines.append(f"--tone-{tone}-{part}:{value};")
    # よく使う別名（--color-success 等）
    lines += [
        "--color-success:var(--tone-success-fg);",
        "--color-warning:var(--tone-warning-fg);",
        "--color-danger:var(--tone-danger-fg);",
        "--color-info:var(--tone-info-fg);",
    ]
    for name, px in FONT_SIZES.items():
        lines.append(f"--font-{name}:{px}px;")
    for name, px in SPACING.items():
        lines.append(f"--space-{name}:{px}px;")
    for name, px in RADIUS.items():
        lines.append(f"--radius-{name}:{px}px;")
    lines.append("--radius-pill:999px;")
    lines.append(f"--shadow:{SHADOW};")
    lines.append(f"--tap-min:{TAP_MIN}px;")
    lines.append(f"--bottom-nav-h:{BOTTOM_NAV_HEIGHT}px;")
    lines.append(f"--max-width:{MAX_WIDTH}px;")
    return "".join(lines)


def dark_variables() -> str:
    """ダーク用の CSS カスタムプロパティ（色だけ。余白・文字サイズはライトと同じ）。"""
    lines = [f"--color-{n}:{v};" for n, v in DARK_BASE_COLORS.items()]
    for tone, vals in DARK_TONES.items():
        lines += [f"--tone-{tone}-{part}:{v};" for part, v in vals.items()]
    return "".join(lines)


def dark_css(scope: str = ':root:not([data-theme="light"])') -> str:
    """OS がダークのときだけ効く規則。scope にはトークンを定義した要素のセレクタを渡す。

    旧ページ（:root に定義）は既定のまま。HOME のように #new-ui-root に定義している場合は
    scope に ':root:not([data-theme="light"]) #new-ui-root' を渡す（#new-ui-root 単独の定義より優先される）。
    data-theme="light" を html に付ければダークを無効にできる。
    """
    return f"@media (prefers-color-scheme:dark){{{scope}{{{dark_variables()}}}}}"


def all_colors() -> set[str]:
    """新UIで使ってよい色の一覧（テストで直書きの色を検出するのに使う）。"""
    colors = set(BASE_COLORS.values()) | set(DARK_BASE_COLORS.values())
    for vals in (*TONES.values(), *DARK_TONES.values()):
        colors.update(vals.values())
    return {c.lower() for c in colors}
