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
    "bg": "#f8fafc",
    "surface": "#ffffff",
    "border": "#e2e8f0",
    "text": "#0f172a",
    "muted": "#475569",
    "subtle": "#64748b",
    # アクセントは青系1色（UI Phase 1）。白背景との文字コントラスト 5.2:1
    "primary": "#2563eb",
    "primary-contrast": "#ffffff",
    "primary-soft": "#eff6ff",
    "focus": "#1d4ed8",
}

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


def all_colors() -> set[str]:
    """新UIで使ってよい色の一覧（テストで直書きの色を検出するのに使う）。"""
    colors = set(BASE_COLORS.values())
    for vals in TONES.values():
        colors.update(vals.values())
    return {c.lower() for c in colors}
