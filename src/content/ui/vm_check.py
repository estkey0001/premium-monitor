"""抽選の表示モデル（VM）が元データと一致するかの突き合わせ（deploy-check #810）。

新UIの抽選の一覧・HOME の件数・閲覧時の状態の計算は、すべて VM（runtime.build_vms が作る）から作る。
VM への変換の誤り（タイムゾーンのずれ・項目の欠落・日付だけの値に時刻を作る・URL の取り違え・印の落ち）は、
画面では気づきにくいので、変換とは別の書き方で元データ（exports/tcg の抽選・旧来の抽選の CSV/DB の値）と比べる。

UI Phase 10 で旧UIとの件数の照合（parity）を削除したときに、旧UIに依存しないこの部分だけを残した。
"""

from __future__ import annotations

# VM の項目（時刻・日付）と exports/tcg の項目（時刻・日付）
_PAIRS = (("as", "application_start", "asd", "application_start_date"),
          ("ae", "application_end", "aed", "application_end_date"),
          ("wa", "winner_announcement_at", "wad", "winner_announcement_date"),
          ("ps", "purchase_start", "psd", "purchase_start_date"),
          ("pe", "purchase_end", "ped", "purchase_end_date"))


def _is_ui_official(url: str) -> bool:
    from src.content.ui.runtime import is_official
    return is_official(url)


def legacy_mismatch(raw: dict, vm: dict) -> bool:
    """旧来の抽選（カメラ・ゲーム機）の元データ1件と VM の1件が食い違うか（日時・応募 URL・情報元 URL）。"""
    from src.tcg.lottery.manual import is_official_url
    from src.tcg.models import parse_dt

    apply_url = str(raw.get("entry_form_url") or "").strip()
    info_url = str(raw.get("url") or "").strip()
    # 応募 URL・情報元 URL は元データと同じもの（応募 URL は公式のものだけ）
    if vm.get("apply") and (vm["apply"] != apply_url
                            or not (is_official_url(vm["apply"]) or _is_ui_official(vm["apply"]))):
        return True
    if vm.get("info") and vm["info"] != info_url:
        return True
    for keys, se, sd in ((("entry_start_at", "entry_start"), "as", "asd"),
                         (("entry_end_at", "entry_end"), "ae", "aed"),
                         (("result_announcement_at",), "wa", "wad")):
        v = next((str(raw.get(k) or "").strip() for k in keys if str(raw.get(k) or "").strip()), "")
        if len(v) >= 16:
            want = parse_dt(v.replace(" ", "T", 1))
            if want is None:
                continue
            if not vm.get(se) or parse_dt(vm[se]) != want:
                return True
        elif v:
            if vm.get(se) or vm.get(sd) != v[:10]:          # 日付だけの値に時刻を作らない
                return True
        elif vm.get(se) or vm.get(sd):
            return True
    return False


def tcg_mismatch(ev: dict, vm: dict) -> bool:
    """exports/tcg の抽選1件と VM の1件が食い違うか（日時・応募 URL・公式情報・結果確認・印）。"""
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


def check(vms: list[dict], tcg_report: dict | None, legacy_items: list | None) -> dict[str, int]:
    """VM と元データの食い違いの件数。{"tcg": 件数, "legacy": 件数, "n": VM の数}。0 なら一致。

    - tcg: exports/tcg の抽選（ENDED を除く）と TCG の VM を順に突き合わせる（件数の差も食い違いに数える）
    - legacy: 旧来の抽選（参考の項目を除く）と VM を id で突き合わせる。VM に無いものは、TCG 側に同じ商品が
      あって新UIが外したときだけ許す。元データに無い VM も食い違いに数える
    """
    from src.content.ui import runtime as rt
    from src.tcg.lottery.schema import product_key

    report = tcg_report if isinstance(tcg_report, dict) else {}
    lots = [e for e in (report.get("lotteries") or []) if isinstance(e, dict) and e.get("status") != "ENDED"]
    tcg_vms = [v for v in vms if v.get("src") == "tcg"]
    bad_tcg = sum(1 for e, v in zip(lots, tcg_vms) if tcg_mismatch(e, v)) + abs(len(tcg_vms) - len(lots))
    leg = {v["id"]: v for v in vms if v.get("src") == "legacy"}
    tcg_names = {product_key(v.get("t") or "") for v in tcg_vms}
    raw_by_id = {}
    for i, raw in enumerate(legacy_items or []):
        it = raw if isinstance(raw, dict) else dict(raw)
        if not it.get("reference_only"):
            raw_by_id.setdefault(rt.legacy_id(it, i), it)          # 同じ id は最初の1件（VM と同じ）
    bad_leg = 0
    for vid, it in raw_by_id.items():
        v = leg.get(vid)
        if v is None:
            name = product_key(str(it.get("product_name") or ""))
            bad_leg += 0 if (name and name in tcg_names) else 1      # TCG 側を優先して外したものだけ許す
        elif legacy_mismatch(it, v):
            bad_leg += 1
    bad_leg += sum(1 for vid in leg if vid not in raw_by_id)
    return {"tcg": bad_tcg, "legacy": bad_leg, "n": len(vms)}
