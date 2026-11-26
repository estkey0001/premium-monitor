"""発見のエンジン（L3 AI Research Engine の第1段階。検索 API と LLM を使わない最小の基盤）。

流れ: 既知の公式ドメインの sitemap・RSS・一覧ページ（frontier）→ 前回に無かった URL（Lead）→ URL の選別（urlpolicy）
→ polite 取得（fetch）→ 根拠つき抽出（extract.rules。LLM は extract.llm の差し込み口だけ）→ 照合（match）
→ 重複排除（dedupe）→ 品質ゲート G1〜G10（gate）→ 既存の台帳（src/discovery/store.py）への振り分け（route）。

エンジンの出力はすべて DISCOVERED（台帳の状態は既存の語彙）。VERIFIED・公開への登録はしない（人の手順
register-event-candidate --confirm だけ）。`publish_ready` は人の確認の並べ替えの印であって検証済みではない。
"""
