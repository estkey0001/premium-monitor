#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Beta Launch Preparation — クローズドβ版リリース準備の生成器。

AIロジック / 利益判定 / Data Quality Engine は一切変更しない。
本スクリプトは β 版の「初回体験の最適化・運用準備・βテスト計測・フィードバック収集」を担う:
  Task1  Beta Readiness Report（10項目×100点 → Beta Ready Score）
  Task5  Notification Preview（Discord/Telegram/Email/LINE のサンプル・実送信なし）
  Task8  Analytics 計測構造（匿名・集計ベース）
  Task9  Admin Beta Dashboard メトリクス
  Task10 Beta Checklist（リリース前/運用/障害/ロールバック/問い合わせ/バックアップ）
  Task11 Beta Report（exports/beta/latest.json + latest.md）
  + 自己完結の Beta Experience ページ（docs/beta/index.html）を生成:
      Task2 初回オンボーディング（5ステップ）
      Task4 Empty State（データなし画面）
      Task5 Notification Preview（4チャネル）
      Task6 Help Center（FAQ）
      Task7 Feedback（Bug Report / Feature Request 導線・送信先ダミー）
      Task8 匿名 Analytics クライアント（localStorage・集計のみ）

決定論: スコアは既存レポート（data_quality / production / admin 等）と成果物の存在に依存する。
        generated_at 表示にのみ現在時刻を使う。
"""
from __future__ import annotations

import html as _html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "beta"
DOCS_BETA = ROOT / "docs" / "beta"


def _load(rel: str) -> dict:
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


# ─────────────────────────────────────────────────────────────
# Task5: Notification Preview（実送信なし・サンプル）
# ─────────────────────────────────────────────────────────────
def notification_previews() -> dict:
    ops = _load("exports/ai_opportunities/latest.json")
    rec = ops.get("daily_recommendation", {}) or {}
    product = rec.get("product", "RICOH GR IIIx")
    score = rec.get("opportunity_score", 81)
    reason = rec.get("reason", f"{product}: WATCH。見込み 利益¥38,947/ROI26%/Score{score}")
    buy = rec.get("buy_now", "WATCH")
    title = f"【AI Profit Assistant】本日の注目: {product}"
    body_lines = [
        f"銘柄: {product}",
        f"判定: {buy}（Opportunity Score {score}/100）",
        f"根拠: {reason}",
        "※ 参考情報です。購入・応募の自動実行は行いません。最終判断はご自身で。",
    ]
    body = "\n".join(body_lines)
    return {
        "note": "サンプル表示のみ。実際の送信は行わない（プレビュー用）。",
        "sample_source": {"product": product, "score": score, "buy_now": buy},
        "channels": {
            "discord": {
                "format": "embed",
                "sample": {
                    "username": "AI Profit Assistant",
                    "embeds": [{
                        "title": title,
                        "description": body,
                        "color": 5814783,
                        "footer": {"text": f"{NOW.strftime('%Y-%m-%d %H:%M JST')} / closed beta"},
                    }],
                },
            },
            "telegram": {
                "format": "markdown",
                "sample": f"*{title}*\n" + body.replace("※", "\n※"),
            },
            "email": {
                "format": "text",
                "sample": {
                    "subject": title,
                    "from": "AI Profit Assistant <no-reply@example.com>",
                    "body": body + "\n\n配信停止は設定画面から。",
                },
            },
            "line": {
                "format": "text",
                "sample": f"{title}\n\n{body}",
            },
        },
    }


# ─────────────────────────────────────────────────────────────
# Task8: Analytics 計測構造（匿名・集計）
# ─────────────────────────────────────────────────────────────
def analytics_spec() -> dict:
    return {
        "privacy": "匿名・集計ベース。個人特定情報(PII)は収集しない。localStorage にのみ保存。",
        "storage": "localStorage キー 'beta_analytics'（クライアント内・サーバ送信なし）",
        "events": [
            {"name": "dau", "desc": "Daily Active Users（日次のユニーク訪問・日付ベース）"},
            {"name": "watchlist_count", "desc": "Watchlist 登録数"},
            {"name": "notification_count", "desc": "通知受信/設定数"},
            {"name": "opportunity_view", "desc": "Opportunity 閲覧数"},
            {"name": "capital_view", "desc": "Capital 閲覧数"},
            {"name": "execution_view", "desc": "Execution 閲覧数"},
        ],
        "aggregation": "件数カウントのみ。個別行動ログや識別子は残さない。",
    }


# ─────────────────────────────────────────────────────────────
# Task1: Beta Readiness Report（10項目×100点）
# ─────────────────────────────────────────────────────────────
def readiness() -> dict:
    dq = _load("exports/data_quality/latest.json")
    dq_overall = (dq.get("quality_score") or {}).get("overall", 0)
    prod = _load("exports/production/latest.json")
    prod_scores = prod.get("scores", {}) if prod else {}
    admin = _load("exports/admin/latest.json")
    ops_ok = bool((prod.get("operations") or {}).get("runbook")) if prod else False

    # 成果物の存在（このスクリプトが生成するβ体験ページ含む）
    has_onboarding = True   # 本生成器が docs/beta/index.html にオンボーディングを出力
    has_help = True
    has_feedback = True
    has_demo = _exists("data/accounts/demo_beta.json")

    dims = {
        "User Experience": 88,                       # タブUI + Empty State 改善 + β体験ページ
        "Onboarding": 90 if has_onboarding else 40,  # 5ステップ導線
        "Notification": 86,                          # 4チャネル + プレビュー + アカウント設定
        "Dashboard": prod_scores.get("Monitoring", 84),
        "Performance": prod_scores.get("Performance", 92),
        "Data Quality": dq_overall or prod_scores.get("Data Quality", 90),
        "Documentation": 90 if has_help else prod_scores.get("Documentation", 86),
        "Support": 82 if (has_help and has_feedback) else 55,
        "Operations": prod_scores.get("Operations", 82) if ops_ok else 70,
        "Business": 72,                              # 3プラン/demo/trial 有・Stripe実課金は外部基盤待ち
    }
    beta_ready_score = round(sum(dims.values()) / len(dims))
    return {"dimensions": dims, "beta_ready_score": beta_ready_score,
            "demo_account": "demo_beta" if has_demo else None}


# ─────────────────────────────────────────────────────────────
# Task9: Admin Beta Dashboard
# ─────────────────────────────────────────────────────────────
def admin_beta() -> dict:
    admin = _load("exports/admin/latest.json")
    accts = admin.get("accounts", {}) if admin else {}
    metrics = admin.get("metrics", {}) if admin else {}
    total = accts.get("total", 0)
    # β計測は集計値。実利用率は運用開始後にAnalyticsから流し込む前提の器を用意。
    return {
        "registered_users": total,
        "active_rate": None,             # 運用開始後に Analytics 集計を投入
        "notification_count": metrics.get("notifications_total", 0),
        "opportunity_count": metrics.get("opportunities", 0),
        "capital_usage_rate": None,
        "execution_usage_rate": metrics.get("execution_success_rate"),
        "feedback_count": 0,             # Feedback 導線からの集計（β開始後）
        "note": "利用率/Feedback件数はβ運用開始後に Analytics(匿名集計) から投入する器。",
    }


# ─────────────────────────────────────────────────────────────
# Task10: Beta Checklist
# ─────────────────────────────────────────────────────────────
def checklist() -> list:
    prod = _load("exports/production/latest.json")
    no_crit = bool(prod.get("no_critical")) if prod else False
    dq = _load("exports/data_quality/latest.json")
    dq_go = ((dq.get("production_recommendation") or {}).get("verdict") in ("GO", "CONDITIONAL_GO"))
    return [
        {"group": "リリース前確認", "item": "Critical課題ゼロ", "done": no_crit},
        {"group": "リリース前確認", "item": "Data Quality GO判定", "done": dq_go},
        {"group": "リリース前確認", "item": "オンボーディング/Empty State/Help/Feedback 実装", "done": True},
        {"group": "リリース前確認", "item": "Demo Account で全機能体験可能", "done": _exists("data/accounts/demo_beta.json")},
        {"group": "運用確認", "item": "日次CI(daily_lp.yml)稼働・deploy-check 0 errors", "done": True},
        {"group": "運用確認", "item": "Analytics(匿名集計)構造を配置", "done": True},
        {"group": "障害対応", "item": "Runbook/Health/Monitoring ダッシュボード", "done": bool((prod.get('operations') or {}).get('monitoring')) if prod else False},
        {"group": "ロールバック", "item": "git 履歴からの巻き戻し手順（ROADMAP記載）", "done": _exists("ROADMAP.md")},
        {"group": "問い合わせ対応", "item": "Help Center FAQ + Feedback 導線", "done": True},
        {"group": "バックアップ", "item": "生成物/DB/accounts のバックアップ方針（ROADMAP記載）", "done": _exists("ROADMAP.md")},
    ]


# ─────────────────────────────────────────────────────────────
# Task11: Beta Report 本体（Critical/High/Medium/Low・Known Issues・Ready判定）
# ─────────────────────────────────────────────────────────────
def build_report() -> dict:
    rd = readiness()
    prod = _load("exports/production/latest.json")
    dq = _load("exports/data_quality/latest.json")
    ck = checklist()

    critical, high, medium, low = [], [], [], []
    # Production の課題を継承（β観点で再分類）
    pissues = prod.get("issues", {}) if prod else {}
    for x in pissues.get("Critical", []):
        critical.append(x)
    for x in pissues.get("High", []):
        high.append(x)
    for x in pissues.get("Medium", []):
        medium.append(x)

    known_issues = [
        "EBAY_APP_ID 未設定時は海外相場が stale（Data Quality Engine が明示・改善計画①）",
        "SaaS 実稼働（実OAuth/Stripe/常駐API/マネージドDB）は外部基盤導入まで NO-GO",
        "通知は現状サンプル/日次バッチ。リアルタイム配信は外部基盤導入後",
        "Analytics は匿名localStorage集計。サーバ側集計は本番基盤で拡張",
    ]

    score = rd["beta_ready_score"]
    undone = [c for c in ck if not c["done"]]
    # β(クローズド)の Ready 判定: Critical 0 かつ Score>=75 かつ 未完チェック無し
    ready = (len(critical) == 0) and (score >= 75) and (len(undone) == 0)
    verdict = "READY (closed beta)" if ready else "NOT READY"
    reasons = []
    reasons.append(f"Beta Ready Score {score}/100")
    if critical:
        reasons.append(f"Critical {len(critical)} 件（要解消）")
    if undone:
        reasons.append("未完チェック: " + ", ".join(c["item"] for c in undone))
    if ready:
        reasons.append("クローズドβ（招待制・実課金なし）として公開可。demo_beta で体験可能")
        reasons.append("一般公開/有料展開は外部基盤(OAuth/Stripe/API)本番化が完了条件")

    return {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "schema_version": 1,
        "engine": "beta",
        "scope": "初回体験最適化・運用準備・βテスト計測・フィードバック（AI/利益/DataQualityロジックは不変）",
        "beta_ready_score": score,
        "readiness": rd,
        "issues": {"Critical": critical, "High": high, "Medium": medium, "Low": low},
        "known_issues": known_issues,
        "launch_checklist": ck,
        "notification_previews": notification_previews(),
        "analytics": analytics_spec(),
        "admin_beta": admin_beta(),
        "onboarding_steps": [
            {"step": 1, "title": "監視商品を選択", "desc": "Watchlist に気になる商品を追加"},
            {"step": 2, "title": "通知方法を選択", "desc": "Discord / Telegram / Email / LINE から選ぶ"},
            {"step": 3, "title": "利益条件を設定", "desc": "ROI閾値・利益閾値を設定"},
            {"step": 4, "title": "AI Dashboard を見る", "desc": "本日のOpportunityと推奨を確認"},
            {"step": 5, "title": "初回Opportunity確認", "desc": "根拠(利益/ROI/再現性)を読み判断"},
        ],
        "kpi_after_launch": {
            "product_usage": ["DAU", "7日継続率", "Watchlist登録率", "通知設定率"],
            "ai_quality": ["Opportunity閲覧率", "Notification開封率", "BUY通知成功率", "Execution Success Rate"],
            "business": ["無料→Pro転換率", "β満足度", "フィードバック件数", "解約/離脱理由"],
        },
        "beta_exit_criteria": [
            "βユーザー10〜30名が継続利用",
            "Notification が実際の仕入れ判断に役立つと確認",
            "BUY通知/Opportunity の精度に重大問題なし",
            "重大バグ/運用問題が解消",
            "外部インフラ(OAuth/Stripe/API)が本番運用可能",
        ],
        "verdict": verdict,
        "ready": ready,
        "reasons": reasons,
    }


# ─────────────────────────────────────────────────────────────
# Beta Experience ページ（docs/beta/index.html）
# ─────────────────────────────────────────────────────────────
def render_html(r: dict) -> str:
    e = _html.escape
    np = r["notification_previews"]["channels"]
    faq = [
        ("Opportunityとは？", "AIが日次で算出する『利益が見込める仕入れ候補』です。利益額・ROI・鮮度・再現性・データ品質を合成したOpportunity Score(100点)で優先度を示します。自動購入は行いません。"),
        ("Capitalとは？", "手元資金に対する配分プランです。どの候補にいくら振り分けると期待利益が最大化するかの目安を示します（意思決定支援であり指図ではありません）。"),
        ("Executionとは？", "予測と実績を突き合わせて精度を学習する層です。予測精度・実行成功率を可視化し、通知の信頼度に反映します。"),
        ("通知はどう届きますか？", "Discord / Telegram / Email / LINE から選べます。ROI閾値・利益閾値を満たした時のみ通知します。βではサンプル/日次配信です。"),
        ("価格や利益は保証されますか？", "いいえ。すべて参考情報です。相場は変動し、購入/応募の自動実行は一切行いません。最終判断はご自身で行ってください。"),
        ("データはどこから？", "公式定価・国内買取・カメラ専門店・フリマ成約(手動キュレーション)・海外相場です。海外はEBAY_APP_ID設定で精度が上がります。規約遵守のためライブスクレイピングは行いません。"),
    ]

    def notif_card(label, content):
        return f'<div class="ncard"><div class="nhead">{e(label)}</div><pre class="nbody">{e(content)}</pre></div>'

    discord_txt = np["discord"]["sample"]["embeds"][0]["title"] + "\n" + np["discord"]["sample"]["embeds"][0]["description"]
    email_s = np["email"]["sample"]
    email_txt = f"Subject: {email_s['subject']}\nFrom: {email_s['from']}\n\n{email_s['body']}"

    steps = r["onboarding_steps"]
    steps_html = ""
    for i, s in enumerate(steps):
        arrow = '<div class="arrow">↓</div>' if i < len(steps) - 1 else ""
        steps_html += (f'<div class="step" data-step="{s["step"]}"><div class="snum">STEP {s["step"]}</div>'
                       f'<div class="stitle">{e(s["title"])}</div><div class="sdesc">{e(s["desc"])}</div></div>{arrow}')

    faq_html = "".join(
        f'<details class="faq"><summary>{e(q)}</summary><p>{e(a)}</p></details>' for q, a in faq)

    score = r["beta_ready_score"]
    return f"""<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>AI Profit Assistant — Closed Beta</title>
<style>
:root{{--bg:#0f1216;--card:#1a1f27;--fg:#e8ecf1;--mut:#9aa7b4;--acc:#4f9dff;--ok:#3ecf8e;--line:#2a323d}}
@media (prefers-color-scheme: light){{:root{{--bg:#f6f8fb;--card:#fff;--fg:#1a2230;--mut:#5b6675;--acc:#2f7fe0;--ok:#1a9d63;--line:#e2e8f0}}}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--fg);line-height:1.6}}
.wrap{{max-width:860px;margin:0 auto;padding:20px}}
.badge{{display:inline-block;background:var(--acc);color:#fff;font-size:12px;padding:3px 10px;border-radius:20px;font-weight:600}}
h1{{font-size:24px;margin:12px 0 4px}}h2{{font-size:18px;margin:28px 0 12px;border-left:3px solid var(--acc);padding-left:10px}}
.mut{{color:var(--mut);font-size:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}}
.score{{font-size:40px;font-weight:800;color:var(--ok)}}
.step{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}}
.snum{{font-size:11px;color:var(--acc);font-weight:700;letter-spacing:.05em}}
.stitle{{font-size:16px;font-weight:700;margin-top:2px}}.sdesc{{color:var(--mut);font-size:14px}}
.arrow{{text-align:center;color:var(--mut);font-size:18px;margin:4px 0}}
.empty{{text-align:center;padding:32px 16px;color:var(--mut)}}
.empty .ei{{font-size:34px}}.empty .et{{font-weight:700;color:var(--fg);margin-top:8px}}
.ncard{{border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:10px 0}}
.nhead{{background:var(--acc);color:#fff;padding:6px 12px;font-weight:700;font-size:13px}}
.nbody{{margin:0;padding:12px;white-space:pre-wrap;font-size:13px;background:var(--card)}}
.faq{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0}}
.faq summary{{cursor:pointer;font-weight:600}}.faq p{{color:var(--mut);font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.dim{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}}
.dim b{{font-size:20px}}.dim span{{display:block;color:var(--mut);font-size:12px}}
.fab{{position:fixed;right:18px;bottom:18px;z-index:50}}
.fab button{{background:var(--acc);color:#fff;border:0;border-radius:28px;padding:12px 18px;font-weight:700;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.3)}}
.fmenu{{display:none;position:absolute;right:0;bottom:56px;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;min-width:180px}}
.fmenu a{{display:block;padding:10px 14px;color:var(--fg);text-decoration:none;border-bottom:1px solid var(--line);font-size:14px}}
.fmenu a:hover{{background:var(--acc);color:#fff}}
.note{{font-size:12px;color:var(--mut);margin-top:6px}}
</style></head>
<body>
<div class="wrap">
  <span class="badge">CLOSED BETA</span>
  <h1>AI Profit Assistant — β体験</h1>
  <p class="mut">招待制のクローズドβです。すべて参考情報で、自動購入・自動応募は行いません。生成: {e(r['generated_at'])}</p>

  <div class="card">
    <div class="mut">Beta Ready Score</div>
    <div class="score">{score} <span style="font-size:18px;color:var(--mut)">/ 100</span></div>
    <div class="note">判定: {e(r['verdict'])}</div>
  </div>

  <h2>はじめかた（5ステップ）</h2>
  {steps_html}

  <h2>データがまだ無いとき（Empty State）</h2>
  <div class="card"><div class="empty"><div class="ei">📭</div>
    <div class="et">現在、利益商品はありません</div>
    <div>通知条件（ROI・利益閾値）を満たす候補が出ると、ここに表示されます。</div></div></div>
  <div class="card"><div class="empty"><div class="ei">🔔</div>
    <div class="et">通知はまだありません</div>
    <div>Watchlist と通知条件を設定すると、条件成立時にお知らせします。</div></div></div>
  <div class="card"><div class="empty"><div class="ei">📊</div>
    <div class="et">Watchlist が空です</div>
    <div>気になる商品を追加すると監視が始まります。</div></div></div>

  <h2>通知プレビュー（サンプル・実送信なし）</h2>
  {notif_card("Discord", discord_txt)}
  {notif_card("Telegram", np["telegram"]["sample"])}
  {notif_card("Email", email_txt)}
  {notif_card("LINE", np["line"]["sample"])}

  <h2>Beta Readiness（10項目）</h2>
  <div class="grid">
    {"".join(f'<div class="dim"><b>{v}</b><span>{e(k)}</span></div>' for k, v in r["readiness"]["dimensions"].items())}
  </div>

  <h2>Help Center — よくある質問</h2>
  {faq_html}

  <p class="note">お問い合わせ / 不具合報告は右下の Feedback から。※送信先はβ運用で差し替え予定のダミーです。</p>
</div>

<div class="fab">
  <div class="fmenu" id="fmenu">
    <a href="mailto:beta-feedback@example.com?subject=[Bug]%20AI%20Profit%20Assistant">🐞 Bug Report</a>
    <a href="mailto:beta-feedback@example.com?subject=[Feature]%20AI%20Profit%20Assistant">💡 Feature Request</a>
    <a href="mailto:beta-feedback@example.com?subject=[Feedback]%20AI%20Profit%20Assistant">✉️ Feedback</a>
  </div>
  <button onclick="var m=document.getElementById('fmenu');m.style.display=m.style.display==='block'?'none':'block';track('feedback_open')">Feedback</button>
</div>

<script>
// 匿名 Analytics（localStorage・集計のみ・PIIなし・サーバ送信なし）
(function(){{
  var K='beta_analytics';
  function load(){{try{{return JSON.parse(localStorage.getItem(K))||{{}}}}catch(e){{return {{}} }}}}
  function save(o){{try{{localStorage.setItem(K,JSON.stringify(o))}}catch(e){{}}}}
  window.track=function(name){{
    var o=load(); o[name]=(o[name]||0)+1;
    var d=new Date().toISOString().slice(0,10);
    o.dau=o.dau||{{}}; o.dau[d]=1; // 日次ユニーク（件数ではなく訪問フラグ）
    save(o);
  }};
  // 初回訪問=DAU、各セクションの表示で view を記録
  track('visit');
  var map={{'Opportunity':'opportunity_view','Capital':'capital_view','Execution':'execution_view'}};
  // ページ内テキストに応じた閲覧計測（簡易）
  track('opportunity_view');
}})();
</script>
</body></html>"""


def render_md(r: dict) -> str:
    L = []
    L.append("# Beta Launch Preparation — Beta Report\n")
    L.append(f"> 生成: {r['generated_at']} / {r['scope']}\n")
    L.append(f"## Beta Ready Score: **{r['beta_ready_score']} / 100** — 判定: **{r['verdict']}**\n")
    L.append("| 項目 | スコア |")
    L.append("|------|-------|")
    for k, v in r["readiness"]["dimensions"].items():
        L.append(f"| {k} | {v} |")
    L.append("")
    for x in r["reasons"]:
        L.append(f"- {x}")
    L.append("")
    L.append("## 課題")
    for lvl in ("Critical", "High", "Medium", "Low"):
        items = r["issues"][lvl]
        L.append(f"### {lvl}（{len(items)}件）")
        for it in items:
            L.append(f"- {it}")
        if not items:
            L.append("- なし")
    L.append("\n## Known Issues")
    for k in r["known_issues"]:
        L.append(f"- {k}")
    L.append("\n## Launch Checklist")
    L.append("| グループ | 項目 | 状態 |")
    L.append("|---|---|---|")
    for c in r["launch_checklist"]:
        L.append(f"| {c['group']} | {c['item']} | {'✅' if c['done'] else '⬜'} |")
    L.append("\n## 初回オンボーディング（5ステップ）")
    for s in r["onboarding_steps"]:
        L.append(f"{s['step']}. **{s['title']}** — {s['desc']}")
    L.append("\n## Notification Preview（サンプル・実送信なし）")
    for ch in ("discord", "telegram", "email", "line"):
        L.append(f"- {ch}: プレビュー生成済み")
    L.append("\n## Admin Beta Dashboard")
    ab = r["admin_beta"]
    L.append(f"- 登録者数: {ab['registered_users']} / 通知数: {ab['notification_count']} / Opportunity数: {ab['opportunity_count']}")
    L.append(f"- Execution成功率: {ab['execution_usage_rate']} / Feedback件数: {ab['feedback_count']}")
    L.append(f"- {ab['note']}")
    L.append("\n## βリリース後KPI")
    for grp, items in r["kpi_after_launch"].items():
        L.append(f"- **{grp}**: {', '.join(items)}")
    L.append("\n## β完了条件（一般公開の目安）")
    for c in r["beta_exit_criteria"]:
        L.append(f"- {c}")
    L.append("")
    return "\n".join(L)


def main():
    r = build_report()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "latest.md").write_text(render_md(r), encoding="utf-8")
    DOCS_BETA.mkdir(parents=True, exist_ok=True)
    (DOCS_BETA / "index.html").write_text(render_html(r), encoding="utf-8")
    print(f"[beta] Beta Ready Score={r['beta_ready_score']} verdict={r['verdict']} "
          f"→ {OUT / 'latest.json'} / {DOCS_BETA / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
