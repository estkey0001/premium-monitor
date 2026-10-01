"""新UIの「抽選・販売」ページ（段階B: 仮ページ）。

段階C で現行の抽選・販売の表示をここへ移す。今は件数の要約と、現行版への導線だけを出す。
件数は runtime.derive_runtime_state の状態で数え、閲覧時はブラウザ側で数え直す（data-nu-sum）。
"""

from __future__ import annotations

from src.content.ui import components as c

# 表示する順番（internal/uiux/NEW_INFORMATION_ARCHITECTURE.md 4章）
GROUPS = ("ENDING_SOON", "OPEN", "UPCOMING", "WINNER_PURCHASE_PERIOD", "SOURCE_CONFLICT",
          "CLOSED", "RESULT_PENDING", "WINNER_ANNOUNCED")


def summarize(vms: list[dict], states: dict[str, dict]) -> dict[str, int]:
    counts = {k: 0 for k in GROUPS}
    for vm in vms:
        if vm.get("ann"):
            continue
        key = states[vm["id"]]["status"]
        if key in counts:
            counts[key] += 1
    return counts


def render(vms: list[dict], states: dict[str, dict], *, has_data: bool) -> str:
    counts = summarize(vms, states)
    rows = "".join(
        f'<li class="nu-sumrow" data-nu-sum="{k}">{c.badge(k)}<span class="nu-sumrow__n">{n}件</span></li>'
        for k, n in counts.items())
    body = (f'<ul class="nu-sumlist">{rows}</ul>' if has_data else
            c.empty_state("NO_DATA", "抽選・販売の情報がまだありません",
                          "最初の取得が終わると表示されます"))
    return (
        '<section class="nu-page" data-nu-page="lottery" aria-labelledby="nu-lottery-title" hidden>'
        '<h1 id="nu-lottery-title" class="nu-page__title">抽選・販売</h1>'
        '<p class="nu-lead">新しい表示は順次公開します。今は件数の要約だけを表示しています。</p>'
        f'{body}'
        + c.button("現行版の抽選・販売を見る", "./?from=new#tab-lottery", kind="secondary")
        + '</section>'
    )
