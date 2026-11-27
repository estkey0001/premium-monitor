"""発見のエンジン: 実行の通し（frontier → 取得 → 抽出 → ゲート → 台帳）。通信しない（fetch を差し替える）。"""
import json
from datetime import datetime
from pathlib import Path

from src.discovery import store as st
from src.discovery.engine.dedupe import ENGINE_ORIGIN, ExistingIndex, build_index
from src.discovery.engine.route import candidate_id
from src.discovery.engine.run import run_engine
from src.discovery.engine.urlpolicy import UrlPolicy
from src.tcg.models import JST

FIX = Path(__file__).parent / "fixtures" / "discovery_engine"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
SITEMAP = "https://www.pokemon-card.com/sitemap.xml"
PKM = "https://www.pokemon-card.com/info/2026/11/"
NEW = PKM + "lottery_new.html"
UPD = PKM + "lottery_updated.html"
REG = {"POKEMON": [{"product_id": "pkm-test", "name": "拡張パック「テストフレア」BOX"}], "ONE_PIECE": []}


class FakeFetch:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        if isinstance(v, tuple):
            return v
        return (None, "http_404") if v is None else (v, "")


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def _setup(tmp_path, prev_urls=None):
    cfg = tmp_path / "frontier.yaml"
    cfg.write_text("schema: 1\nsources:\n  - id: pkm_sitemap\n    kind: sitemap\n    url: " + SITEMAP +
                   "\n    enabled: true\n    checked_on: '2026-11-26'\n    include: [lottery]\n", encoding="utf-8")
    priv, ledger = tmp_path / "private", tmp_path / "ledger"
    priv.mkdir()
    prev = prev_urls if prev_urls is not None else {PKM + "lottery_old.html": "2026-10-01", UPD: "2026-11-01"}
    (priv / "frontier_state.json").write_text(json.dumps(
        {"sources": {"pkm_sitemap": {"url": SITEMAP, "kind": "sitemap", "urls": prev}}}), encoding="utf-8")
    return cfg, priv, ledger


def _pages(**over):
    p = {SITEMAP: _read("sitemap.xml"), NEW: _read("lottery_page.html"), UPD: (None, "http_404")}
    p.update(over)
    return p


def _run(tmp_path, cfg, priv, ledger, fetch, now=NOW, apply=True, **kw):
    return run_engine(now=now, fetch=fetch, apply=apply, config_path=cfg, private_dir=priv, ledger_dir=ledger,
                      registry=kw.pop("registry", REG), existing=kw.pop("existing", ExistingIndex()),
                      policy=UrlPolicy(excluded={}), **kw)


def test_dry_run_writes_nothing(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    before = sorted(p.name for p in priv.rglob("*"))
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()), apply=False)
    assert rep["leads"] == 2 and rep["publish_ready"] == 1 and not rep["applied"]
    assert not ledger.exists() and sorted(p.name for p in priv.rglob("*")) == before


def test_apply_writes_ledger_without_quotes_or_price(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    ff = FakeFetch(_pages())
    rep = _run(tmp_path, cfg, priv, ledger, ff)
    assert ff.calls == [SITEMAP, NEW, UPD]                       # sitemap と新しい URL だけ（古い URL は取らない）
    assert rep["routed"] == {st.ANNOUNCEMENT_REVIEW_REQUIRED: 1} and rep["publish_ready"] == 1
    data = st.load(ledger / st.EVENT_FILE)
    rec = data["candidates"][candidate_id(NEW)]
    assert rec["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED and rec["publish_ready"] is True
    assert rec["origin"] == ENGINE_ORIGIN and rec["kind"] == "LOTTERY" and rec["product_id"] == "pkm-test"
    # 告知の候補の正式な日程の欄は空（#862）。根拠つきで読めた日程は engine_schedule に分けて持つ
    assert rec["application_start"] is None and rec["application_end"] is None
    assert rec["engine_schedule"]["application_start"] == "2026-11-27T12:00:00+09:00"
    assert rec["missing_fields"] == []
    assert rec["event_status"] == "UPCOMING"
    assert rec["engine_evidence"]["doc_id"] and rec["engine_evidence"]["positions"]["application_start"]
    raw = (ledger / st.EVENT_FILE).read_text(encoding="utf-8")
    for leak in ("5,400", "5400", "会員登録がお済み", "4521329000015", "quote", "11月27日（金）12:00"):
        assert leak not in raw, leak                             # 公開の台帳に quote 本文・価格・JAN を書かない
    # 非公開のほうに根拠（quote）が残る
    run = json.loads((priv / "engine_run.json").read_text(encoding="utf-8"))
    assert run["rows"][0]["rules"]["fields"]["application_start"]["evidence"]["quote"] == "11月27日（金）12:00"
    assert (priv / "docs" / "index.json").exists() and (priv / "leads.json").exists()
    leads = json.loads((priv / "leads.json").read_text(encoding="utf-8"))["leads"]
    assert all(set(ld) & {"title", "snippet", "description"} == set() for ld in leads)


def test_ledger_passes_deploy_check_862_shape(tmp_path):
    """deploy-check #862 と同じ形の検査: 候補の ID・状態・discovered_at・告知の候補に日程が無い。"""
    cfg, priv, ledger = _setup(tmp_path)
    _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()))
    for cid, r in st.load(ledger / st.EVENT_FILE)["candidates"].items():
        assert r["candidate_id"] == cid and r["status"] in st.STATUSES and r["discovered_at"]
        if r["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED:
            assert not (r.get("application_start") or r.get("application_end"))


def test_engine_never_sets_human_or_verified_states(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()))
    statuses = {r["status"] for r in st.load(ledger / st.EVENT_FILE)["candidates"].values()}
    assert statuses <= {st.ANNOUNCEMENT_REVIEW_REQUIRED, st.REVIEW_REQUIRED}
    assert not statuses & {st.APPROVED, st.REGISTERED, st.REJECTED, "VERIFIED"}


def test_human_decision_is_not_overwritten_and_same_content_keeps_updated_at(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()))
    path = ledger / st.EVENT_FILE
    data = st.load(path)
    cid = candidate_id(NEW)
    first_updated = data["candidates"][cid]["updated_at"]
    # 同じ内容で見つけ直す（sitemap の lastmod が進んだ・本文は同じ）→ 本文が同じなので抽出し直さず、時刻も進めない
    later = datetime(2026, 11, 26, 18, 0, tzinfo=JST)
    sm = _read("sitemap.xml").replace("<lastmod>2026-11-20</lastmod>", "<lastmod>2026-11-25</lastmod>")
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages(**{SITEMAP: sm})), now=later)
    assert rep["unchanged_body"] == 1
    assert st.load(path)["candidates"][cid]["updated_at"] == first_updated
    # 人が承認したあと、本文が変わって見つけ直しても APPROVED のまま
    data = st.load(path)
    data["candidates"][cid]["status"] = st.APPROVED
    st.save(path, data)
    sm2 = sm.replace("<lastmod>2026-11-25</lastmod>", "<lastmod>2026-11-26</lastmod>")
    body2 = _read("lottery_page.html").replace("会員登録がお済みのお客様", "アプリ会員のお客様")
    _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages(**{SITEMAP: sm2, NEW: body2})), now=later)
    assert st.load(path)["candidates"][cid]["status"] == st.APPROVED


def test_blocked_host_candidates_are_not_used(tmp_path):
    cfg, priv, ledger = _setup(tmp_path, prev_urls={})
    # 新しい URL の本文を取れたが、同じホストの次のページで 403 → そのホストのものはこの実行で使わない
    pages = _pages(**{UPD: (None, "http_403")})
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(pages))
    assert rep["routed"] == {} and rep["dropped"].get("G10:source_blocked_in_run") == 1
    assert not (priv / "docs" / "index.json").exists() or json.loads(
        (priv / "docs" / "index.json").read_text(encoding="utf-8")) == {}


def test_stale_only_for_hosts_read_this_run(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    ledger.mkdir()
    old = {"origin": ENGINE_ORIGIN, "source": "engine:www.pokemon-card.com", "official_url": PKM + "gone.html",
           "status": st.ANNOUNCEMENT_REVIEW_REQUIRED, "last_seen_on": "2026-11-10", "reasons": []}
    listed = dict(old, official_url=PKM + "lottery_old.html")
    other = dict(old, source="engine:www.onepiece-cardgame.com", official_url="https://www.onepiece-cardgame.com/x")
    human = dict(old, official_url=PKM + "human.html", status=st.REJECTED)
    store = {"schema": 1, "candidates": {}}
    for rec in (old, listed, other, human):
        cid = candidate_id(rec["official_url"])
        store["candidates"][cid] = dict(rec, candidate_id=cid)
    st.save(ledger / st.EVENT_FILE, store)
    _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()))
    got = st.load(ledger / st.EVENT_FILE)["candidates"]
    assert got[candidate_id(PKM + "gone.html")]["status"] == st.STALE          # 読めたホストで見えなくなった
    assert got[candidate_id(PKM + "lottery_old.html")]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED  # 一覧に今も並ぶ
    assert got[candidate_id(PKM + "lottery_old.html")]["last_seen_on"] == "2026-11-26"
    assert got[candidate_id("https://www.onepiece-cardgame.com/x")]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED  # 読んでいないホスト
    assert got[candidate_id(PKM + "human.html")]["status"] == st.REJECTED


def test_failed_frontier_does_not_age_out(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    ledger.mkdir()
    rec = {"origin": ENGINE_ORIGIN, "source": "engine:www.pokemon-card.com", "official_url": PKM + "gone.html",
           "status": st.ANNOUNCEMENT_REVIEW_REQUIRED, "last_seen_on": "2026-11-01", "reasons": []}
    cid = candidate_id(rec["official_url"])
    st.save(ledger / st.EVENT_FILE, {"schema": 1, "candidates": {cid: dict(rec, candidate_id=cid)}})
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch({SITEMAP: (None, "robots_unreachable")}))
    assert rep["sources"]["failed"] == 1 and rep["aged_out"] == {"stale": 0, "dropped": 0}
    assert st.load(ledger / st.EVENT_FILE)["candidates"][cid]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED


def test_duplicate_of_existing_lottery_is_not_added(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    lots = tmp_path / "lotteries.json"
    lots.write_text(json.dumps({"items": [{"lottery_id": "lot-1", "source_url": NEW}], "announcements": []}),
                    encoding="utf-8")
    idx = build_index(lotteries_path=lots, manual_csv=tmp_path / "none.csv", event_store={})
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()), existing=idx)
    assert rep["dropped"] == {"G8:duplicate_of": 1}
    assert st.load(ledger / st.EVENT_FILE)["candidates"] == {}


def test_existing_index_ignores_engine_candidates_and_reads_csv(tmp_path):
    csvp = tmp_path / "m.csv"
    csvp.write_text("product,source_url,entry_url\nx,https://www.geo-online.co.jp/a/,\n", encoding="utf-8")
    store = {"candidates": {"a": {"origin": ENGINE_ORIGIN, "official_url": NEW},
                            "b": {"official_url": "https://www.pokemon-card.com/info/b.html"}}}
    idx = build_index(lotteries_path=tmp_path / "none.json", manual_csv=csvp, event_store=store)
    assert idx.find("https://www.geo-online.co.jp/a") == "manual_csv"
    assert idx.find(NEW) is None
    assert idx.find("https://www.pokemon-card.com/info/b.html") == "candidate:b"


def test_unofficial_lead_is_not_fetched(tmp_path):
    cfg, priv, ledger = _setup(tmp_path, prev_urls={})
    sm = _read("sitemap.xml")
    ff = FakeFetch(_pages(**{SITEMAP: sm}))
    rep = _run(tmp_path, cfg, priv, ledger, ff, apply=False)
    assert all("other.example.com" not in u for u in ff.calls)
    assert rep["search"]["provider"] == "null" and rep["search"]["hits"] == 0 and rep["search"]["leads"] == 0


def test_no_config_means_nothing_happens(tmp_path):
    ff = FakeFetch({})
    rep = run_engine(now=NOW, fetch=ff, apply=False, config_path=tmp_path / "missing.yaml",
                     private_dir=tmp_path / "p", ledger_dir=tmp_path / "l", registry=REG, existing=ExistingIndex())
    assert ff.calls == [] and rep["leads"] == 0 and rep["sources"]["used"] == 0


def test_unfetched_leads_are_retried_next_run(tmp_path):
    """本文を取れなかった Lead（404・取得枠の超過・遮断）は既知にしない。次の実行でもう一度 Lead になる（黙って取りこぼさない）。"""
    cfg, priv, ledger = _setup(tmp_path)
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages()))          # UPD は 404
    assert rep["retry_next_run"] == 1
    state = json.loads((priv / "frontier_state.json").read_text(encoding="utf-8"))
    urls = state["sources"]["pkm_sitemap"]["urls"]
    assert UPD not in urls and NEW in urls
    ff = FakeFetch(_pages())
    rep2 = _run(tmp_path, cfg, priv, ledger, ff)
    assert UPD in ff.calls and NEW not in ff.calls


def test_budget_overflow_is_carried_over_and_fetched_next_run(tmp_path):
    """取得枠を超えた Lead は次の実行に持ち越す（連続 2 回の実行で確かめる）。"""
    cfg, priv, ledger = _setup(tmp_path)
    pages = _pages(**{UPD: _read("lottery_page.html")})
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(pages), page_budget=(1, 1))
    assert rep["fetch_state"].get("SKIPPED_BUDGET") == 1 and rep["retry_next_run"] == 1
    ff = FakeFetch(pages)
    rep2 = _run(tmp_path, cfg, priv, ledger, ff, page_budget=(1, 1))
    fetched2 = [u for u in ff.calls if u in (NEW, UPD)]
    assert len(fetched2) == 1 and rep2["retry_next_run"] == 0          # 前回取れなかった 1 件だけを取る


def test_blocked_source_is_stopped_not_retried(tmp_path):
    """403 で遮断された取得元の Lead は、次の実行で取り直さない（停止扱い）。"""
    cfg, priv, ledger = _setup(tmp_path)
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages(**{UPD: (None, "http_403")})))
    assert rep["stopped_blocked"] == 1                                  # 遮断された URL だけを停止に記録する
    assert rep["retry_next_run"] == 1                                   # 先に正常に取れた URL（後でホストが遮断）は次の実行で取り直す
    state = json.loads((priv / "frontier_state.json").read_text(encoding="utf-8"))
    assert state.get("stopped")
    ff = FakeFetch(_pages())
    _run(tmp_path, cfg, priv, ledger, ff)
    assert UPD not in ff.calls


def test_stopped_url_is_not_refetched_even_if_lastmod_advances(tmp_path):
    cfg, priv, ledger = _setup(tmp_path)
    _run(tmp_path, cfg, priv, ledger, FakeFetch(_pages(**{UPD: (None, "http_403")})))
    newer = _read("sitemap.xml").replace("2026-11-21", "2026-12-01")       # UPD の lastmod を進める
    ff = FakeFetch(_pages(**{SITEMAP: newer}))
    _run(tmp_path, cfg, priv, ledger, ff, now=NOW)
    assert UPD not in ff.calls


def test_urls_skipped_by_the_cutoff_are_retried_and_expired_stops_return(tmp_path):
    """遮断で打ち切って要求していない URL は停止扱いにせず次回に回す。停止は期限の後に Lead に戻って一度だけ試す。"""
    from datetime import timedelta
    cfg, priv, ledger = _setup(tmp_path, prev_urls={})
    pages = _pages(**{NEW: (None, "http_403"), UPD: _read("lottery_page.html")})
    rep = _run(tmp_path, cfg, priv, ledger, FakeFetch(pages), bootstrap=True)
    assert rep["stopped_blocked"] == 1                                   # 要求して 403 だった NEW だけ
    state = json.loads((priv / "frontier_state.json").read_text(encoding="utf-8"))
    assert list(state["stopped"]) and UPD not in str(state["stopped"])
    later = NOW + timedelta(days=31)
    ff = FakeFetch(_pages())
    _run(tmp_path, cfg, priv, ledger, ff, now=later)
    assert NEW in ff.calls                                               # 期限の後に一度だけ試し直す
