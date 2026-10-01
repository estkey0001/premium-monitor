"""新旧UIの件数の照合（?debug=1 の表と deploy-check #810 で使う）。

旧UI側は「実際に描画した HTML」から数える（DB や exports の件数ではない）。
新旧で数え方が違うところは、差の理由を次の3種類に分けて数える。説明できない差だけを不一致にする。

- runtime: 新UIは LP 生成時刻で状態を計算し直す。旧UIは exports/tcg の生成時点の状態をそのまま使う
- cap: 旧UIは1グループに表示する件数に上限がある（20件・日程要確認は10件）
- guard: 新UIの表示ガード（0円・極端な利益率などの BUY を出さない）・HOME に出さない ALERT
"""

from __future__ import annotations

import re

from src.content.ui import components as c

# 旧UIの抽選グループの見出し（daily_lp_generator._section_tcg_lottery）→ 状態
_OLD_GROUPS = (
    ("&#9888;&#65039; 日程要確認", "SOURCE_CONFLICT", 10),
    ("&#127919; 抽選受付中", "OPEN", 20),
    ("&#9200; 締切間近", "ENDING_SOON", 20),
    ("&#128197; まもなく抽選開始", "UPCOMING", 20),
    ("&#127942; 当選発表・購入期間", "AFTER", 20),
    ("&#128227; 抽選告知あり", "ANNOUNCEMENT", 10),
)
_AFTER = ("CLOSED", "RESULT_PENDING", "WINNER_ANNOUNCED", "WINNER_PURCHASE_PERIOD")


def old_ui_counts_from_html(html: str) -> dict[str, int]:
    """旧UIが描画した HTML から、抽選カード・AI Opportunities のカードを数える。"""
    out = {k: 0 for _, k, _ in _OLD_GROUPS}
    start = html.find('<div id="category-tcg-lottery"')
    ends: list[int] = []
    if start >= 0:
        # 抽選セクションの終わり（監視元の表、無ければ次の「販売・入荷・プレミア」）
        ends = [i for i in (html.find('<details class="tcg-health">', start),
                            html.find('<div class="tcg-subhead">販売・入荷', start)) if i > 0]
        seg = html[start:min(ends)] if ends else html[start:]
        for chunk in seg.split('<div class="tcg-lot-group">')[1:]:
            for label, key, _cap in _OLD_GROUPS:
                if chunk.startswith(label):
                    out[key] += chunk.count('tcg-lot-card"')
                    break
    out["lottery_total"] = sum(out[k] for _, k, _ in _OLD_GROUPS)
    acts = re.findall(r'<div class="ai-op-card".*?<div style="font-weight:700">#\d+ .*?<span [^>]*>'
                      r'([A-Z_]+)</span>', html, re.S)
    out["opportunities"] = len(acts)
    out["buy"] = sum(1 for a in acts if a == "BUY")
    out["found_lottery_section"] = int(start >= 0 and bool(ends))
    return out


def _group(item: dict, status: str) -> str:
    """旧UIの抽選グループ（_section_tcg_lottery と同じ振り分け）。表示されないものは空文字。"""
    if item.get("conflict"):
        return "SOURCE_CONFLICT"
    if item.get("announcement_only") or item.get("ann"):
        return "ANNOUNCEMENT"
    if status in ("OPEN", "ENDING_SOON", "UPCOMING"):
        return status
    if status in _AFTER:
        return "AFTER"
    return ""


_CAPS = {k: cap for _, k, cap in _OLD_GROUPS}


_PAIRS = (("as", "application_start", "asd", "application_start_date"),
          ("ae", "application_end", "aed", "application_end_date"),
          ("wa", "winner_announcement_at", "wad", "winner_announcement_date"),
          ("ps", "purchase_start", "psd", "purchase_start_date"),
          ("pe", "purchase_end", "ped", "purchase_end_date"))


def _is_ui_official(url: str) -> bool:
    from src.content.ui.runtime import is_official
    return is_official(url)


def _legacy_time_mismatch(raw: dict, vm: dict) -> bool:
    """旧来の抽選の元データ（開始・締切）と VM の日時が食い違うか。"""
    from src.tcg.models import parse_dt
    from src.tcg.lottery.manual import is_official_url

    # 応募 URL・情報元 URL は元データと同じもの（応募 URL は公式のものだけ）
    if vm.get("apply") and (vm["apply"] != raw.get("apply", "").strip()
                            or not (is_official_url(vm["apply"]) or _is_ui_official(vm["apply"]))):
        return True
    if vm.get("info") and vm["info"] != raw.get("info", "").strip():
        return True
    for key, se, sd in (("start", "as", "asd"), ("end", "ae", "aed"), ("result", "wa", "wad")):
        v = str(raw.get(key) or "").strip()
        if len(v) >= 16:
            want = parse_dt(v.replace(" ", "T", 1))
            if want is None:
                continue
            if not vm.get(se) or parse_dt(vm[se]) != want:
                return True
        elif v:
            if vm.get(se) or vm.get(sd) != v[:10]:
                return True
        elif vm.get(se) or vm.get(sd):
            return True
    return False


def _date_in_exact(ev: dict) -> bool:
    """日時の欄に日付だけ（時刻なし）の値が入っているか。"""
    for _se, ke, _sd, _kd in _PAIRS:
        raw = str(ev.get(ke) or "").strip()
        if raw and len(raw) < 16:
            return True
    return False


def _field_mismatch(ev: dict, vm: dict) -> bool:
    """exports の1件と VM の1件が食い違うか（VM 変換とは別の書き方で確かめる）。"""
    from src.tcg.lottery.manual import is_official_url
    from src.tcg.models import parse_dt

    for se, ke, sd, kd in _PAIRS:
        raw = str(ev.get(ke) or "").strip()
        if len(raw) >= 16 and parse_dt(raw) is not None:
            if not vm.get(se) or parse_dt(vm[se]) != parse_dt(raw):
                return True
        else:
            want = (str(ev.get(kd) or "") or raw)[:10]
            got = vm.get(sd) or ""
            if vm.get(se) or (bool(want) != bool(got)) or (want and got != want):
                return True
    url = str(ev.get("entry_url") or "")
    plain = (url.startswith("https://") and is_official_url(url)
             and not any(c in url for c in "\\@ ") and "%5c" not in url.lower())
    if vm.get("apply") and (vm["apply"] != url or not is_official_url(url)):
        return True
    if plain and vm.get("apply") != url:
        return True
    # 公式情報（source_url）は元データと同じ URL だけ
    if vm.get("info") and vm["info"] != str(ev.get("source_url") or "").strip():
        return True
    # 結果確認・購入の URL は公式のものだけ
    for key, short in (("result_url", "result"), ("purchase_url", "purchase")):
        if vm.get(short) and (vm[short] != ev.get(key) or not is_official_url(vm[short])):
            return True
    # 確認待ち・参考情報（「応募する」を出さない印）が元データと合っているか
    unconfirmed = ((ev.get("collection_method") == "MANUAL_VERIFIED" and not ev.get("verified"))
                   or str(ev.get("confidence") or "").lower() == "low") and not ev.get("conflict")
    if bool(vm.get("unv")) != unconfirmed:
        return True
    return bool(ev.get("conflict")) != bool(vm.get("conflict")) or \
        bool(ev.get("announcement_only")) != bool(vm.get("ann"))


def build(model, tcg_report: dict | None, old: dict[str, int]) -> list[dict]:
    """照合表の行。

    - old: 旧UIが描画したカード数
    - exported: exports/tcg の状態で数えた件数（旧UIはこれを上限つきで描画する）
    - home_at_export: 新UIの判定を exports の生成時刻で行った件数（exported と一致するはず。
      違えば VM への変換の誤り）
    - home: 新UIの判定を LP 生成時刻で行った件数（閲覧時はさらにブラウザで計算し直す）
    unexplained = (home_at_export − exported) + (exported − 上限で隠れた分 − old)。0 以外は不一致。
    """
    from src.content.ui import runtime as rt
    from src.tcg.models import parse_dt

    report = tcg_report if isinstance(tcg_report, dict) else {}
    lots = [e for e in (report.get("lotteries") or [])
            if isinstance(e, dict) and e.get("status") != "ENDED"]
    tcg_vms = [v for v in model.vms if v.get("src") == "tcg"]
    at = parse_dt(report.get("generated_at"))
    at_states = ({v["id"]: rt.derive_runtime_state(v, at)["status"] for v in tcg_vms}
                 if at else None)

    def groups_of(items):
        out: dict[str, int] = {}
        for g in items:
            if g:
                out[g] = out.get(g, 0) + 1
        return out

    g_exp = groups_of(_group(e, str(e.get("status") or "")) for e in lots)
    g_now = groups_of(_group(v, model.states[v["id"]]["status"]) for v in tcg_vms)
    pairs = list(zip(lots, tcg_vms))
    if at_states is not None:
        g_at = groups_of(_group(v, at_states[v["id"]]) for v in tcg_vms)
        # 日時の欄に日付だけが入っている抽選は、exports（0:00 とみなす）と新UI（日付として扱い、
        # 時刻を作らない）で判定が違ってよい。その分は exports の状態に置き換えて「ガード」に数える
        g_adj = groups_of(_group(v, str(e.get("status") or "") if _date_in_exact(e) else at_states[v["id"]])
                          for e, v in pairs)
    else:
        g_at = g_adj = dict(g_exp)

    def make(key, label, keys):
        exported = sum(g_exp.get(k, 0) for k in keys)
        shown_old = sum(min(g_exp.get(k, 0), _CAPS[k]) for k in keys)
        home = sum(g_now.get(k, 0) for k in keys)
        home_at = sum(g_at.get(k, 0) for k in keys)
        home_adj = sum(g_adj.get(k, 0) for k in keys)
        o = sum(old.get(k, 0) for k in keys) if key != "lottery_total" else old.get(key, 0)
        return {"key": key, "label": label, "old": o, "home": home,
                "runtime": home - home_at, "cap": exported - shown_old, "guard": home_at - home_adj,
                "unexplained": (home_adj - exported) + (shown_old - o)}

    rows = [
        make("lottery_total", "抽選の合計", [k for _, k, _ in _OLD_GROUPS]),
        make("OPEN", "抽選受付中", ["OPEN"]),
        make("ENDING_SOON", "締切間近", ["ENDING_SOON"]),
        make("UPCOMING", "まもなく開始", ["UPCOMING"]),
        make("SOURCE_CONFLICT", "日程要確認", ["SOURCE_CONFLICT"]),
    ]
    # 1件ずつの突き合わせ: exports の値と VM の値（日時・応募 URL・印）が一致するか。
    # VM 変換の誤り（タイムゾーンのずれ・項目の欠落・URL の取り違え）はここで見つかる
    mism = sum(1 for e, v in zip(lots, tcg_vms) if _field_mismatch(e, v))
    rows.append({"key": "vm_fields", "label": "1件ずつの突き合わせ", "home": len(tcg_vms),
                 "old": len(lots), "runtime": 0, "cap": 0, "guard": 0,
                 "unexplained": mism + abs(len(tcg_vms) - len(lots))})
    # 旧来の抽選（カメラ・ゲーム機）の受付中。旧UIの判定（_count_as_active）を1件ずつ受け取り、
    # 新UIの判定と突き合わせる。違ってよいのは次の2つだけ（ガードに数える）:
    #   - 日付だけの開始・締切（旧UIは 0:00 とみなし、新UIは時刻を作らず日付として扱う）
    #   - TCG 側に同じ商品があるので新UIでは外したもの
    leg_old = old.get("legacy_active_by_id")
    if isinstance(leg_old, dict):
        from src.tcg.lottery.schema import product_key
        leg = {v["id"]: v for v in model.vms if v.get("src") == "legacy"}
        tcg_names = {product_key(v["t"]) for v in tcg_vms}
        home_n = sum(1 for v in leg.values() if model.states[v["id"]]["open"])
        old_n = sum(1 for o in leg_old.values() if o.get("active"))
        guard = bad = 0
        for vid, o in leg_old.items():
            v = leg.get(vid)
            was = bool(o.get("active"))
            now_open = bool(v and model.states[vid]["open"])
            # 違ってよいかは元データ（旧UIに渡した値）だけで決める。VM の値は検証対象なので使わない
            raw_date_only = any(x and len(x.strip()) < 16 for x in (o.get("start"), o.get("end")))
            dup = bool(product_key(o.get("name") or "")) and product_key(o.get("name") or "") in tcg_names
            if v is None:
                if dup:
                    guard -= int(was)          # TCG 側を優先して外した
                else:
                    bad += 1                   # 新UIから理由なく消えた
                continue
            if _legacy_time_mismatch(o, v):
                bad += 1
                continue
            if now_open != was:
                if raw_date_only:
                    guard += int(now_open) - int(was)
                else:
                    bad += 1
        bad += sum(1 for vid in leg if vid not in leg_old)
        rows.append({"key": "legacy_open", "label": "旧来の抽選の受付中", "home": home_n,
                     "old": old_n, "runtime": 0, "cap": 0, "guard": guard, "unexplained": bad})
    buy_new = sum(1 for a in model.opp_cards if a.action == "BUY")
    rows.append({"key": "buy", "label": "BUY（買う）", "home": buy_new, "old": old.get("buy", 0),
                 "runtime": 0, "cap": 0, "guard": -model.hidden_prices,
                 "unexplained": buy_new - (old.get("buy", 0) - model.hidden_prices)})
    opp_new = len(model.opp_cards)
    rows.append({"key": "opportunities", "label": "AI Opportunities", "home": opp_new,
                 "old": old.get("opportunities", 0), "runtime": 0, "cap": 0,
                 "guard": -(model.hidden_prices + model.alert_count),
                 "unexplained": opp_new - (old.get("opportunities", 0)
                                           - model.hidden_prices - model.alert_count)})
    return rows


def render(rows: list[dict], *, hidden_prices: int) -> str:
    """?debug=1 のときだけ表示する件数の照合表（一般公開では隠す）。"""
    body = "".join(
        f'<tr data-parity="{c.esc(r["key"])}" data-match="{"1" if r["unexplained"] == 0 else "0"}">'
        f'<td>{c.esc(r["label"])}</td><td>{r["old"]}</td><td>{r["home"]}</td>'
        f'<td>{r["runtime"]:+d}</td><td>{r["cap"]:+d}</td><td>{r["guard"]:+d}</td>'
        f'<td>{r["unexplained"]:+d}</td></tr>'
        for r in rows)
    return ('<section class="nu-debug" data-nu-debug hidden aria-label="件数の照合（開発用）">'
            '<h2 class="nu-h2">件数の照合（開発用）</h2>'
            f'<p>表示ガードで外した BUY: {hidden_prices}件。差の理由: 時刻＝閲覧時刻での状態の'
            '計算し直し、上限＝旧UIの表示件数の上限、ガード＝新UIの表示ガード。</p>'
            '<div class="nu-debug__scroll"><table><thead><tr><th>項目</th><th>旧UI</th>'
            '<th>新UI</th><th>時刻</th><th>上限</th><th>ガード</th><th>不明</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></section>')
