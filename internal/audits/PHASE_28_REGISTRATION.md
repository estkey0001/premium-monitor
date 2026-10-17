# Phase 28 — 発見の候補の確認と正本への登録

作成: 2026-10-17。Phase 27 で自動発見した候補を、人が確かめたうえで1件ずつ正本に入れる手順。承認と登録を分ける。
TCG は利益に接続しない。外部への送信 0。

## 1. 開始の時点

| 指標 | 値 |
|---|---:|
| 正本の商品 | 45 |
| 商品の候補（台帳） | 27（Apple 7・TCG 20） |
| 確認待ち / 要確認 / 承認 / 却下 / STALE | 13 / 14 / 0 / 0 / 0 |
| 未登録の公式の部品番号 | 20 |
| 告知の候補（要確認） | 2（ほかに正式なイベント 12） |
| Phase 24 の受入状態 | PHASE24_WAITING |
| CI の所要時間 | 1時間14分 |
| pytest | 2010 passed |

## 2. 状態の意味（`src/discovery/store.py`）

- APPROVED: 人が公式ページで「この候補は正しい商品だ」と確かめた。正本・seed・買取の照合・公式の登録簿は変えない
- REGISTERED（新規）: 正本（`config/products.yaml`・手で確認した抽選の CSV）に登録した。人の判断として発見で上書きしない
- 承認できるのは確認待ち・要確認・正式なイベント・却下（取り消し）。STALE は承認できない（公式で見つけ直されて確認待ちに
  戻ってから）。登録済みは却下できない（正本の差分を git で戻す）
- 判断の記録: `review`（最新）と `decisions`（履歴）に時刻・判断・却下の理由（duplicate / not_target / variant_only /
  bad_parse / unsupported / obsolete）・確かめた証拠（official_url・part_numbers・capacity・colors・official_price・
  schedule・product_code）。個人名・メールは残さない
- 登録を戻した（正本に無い）のに台帳が REGISTERED のときは、次回の発見で確認待ちに戻す（`registered_not_in_canonical`）

## 3. 商品の登録（`src/discovery/register.py`・`register-product-candidate`）

- 前提: APPROVED かつ承認で official_url・part_numbers・capacity・official_price を確かめた記録・7日以内に公式で見た・発見元が Apple 公式・購入ページの URL・日本向けの
  部品番号（`^[A-Z0-9]{4,5}J/A$`）・機種と容量が候補名と一致・色で変わらない1つの価格・TCG でない
- 重複の防止: product_id・「機種 + 容量」（正本の名前から）・部品番号（型番・keywords・part_numbers）・JAN・照合済み
- product_id は既存の規則（`prod_iphone17pm_256`。TB は `prod_iphoneduo_1tb`）。手入力の ID は受けない
- 項目: 既存の形（id・genre・name「機種 容量 SIMフリー」・brand・model_number は空・retail_price・keywords）＋証拠
  （capacity・part_numbers・colors・official_url・price_observed_on）。候補の ID は正本に書かない（#862 は候補の ID が正本に
  あれば自動で入ったとみなす）。keywords の先頭は容量つきの名前（API・旧来の取得の検索語。機種名だけにすると別の容量に当たる）
- 置き場所: 最後の iPhone の後ろ（初回だけ見出しのコメント）。既存の行・コメント・並びは変えない
- 既定は dry-run（候補・新しい product_id・項目・正本の差分・監視への影響）。`--confirm` のときだけ、手元の正本が main と同じ
  （`outbox.main_ledger_matches`）・手元の台帳が main の台帳とこの候補の判断の項目だけ違う（`ledgers_match_except`。この候補の
  価格・部品番号などは同じ・main で却下 / 登録済みになっていない）かを確かめ、YAML として読める・既存は不変・足すのは1件だけを確かめてから一時ファイル経由で
  置き換え、台帳を REGISTERED にする（台帳の保存に失敗したら正本を元に戻す）。commit / push はしない（2つのファイルだけを
  コミットするコマンド・push・取り消し方を表示）
- 取り消し: 正本のその1件の差分だけを戻す（台帳は CI の生成で変わるので戻さない）。`discover` が毎回（機種のページを読むかに
  依らず）正本と台帳の REGISTERED を照らし合わせ（`reconcile_registered`）、正本に無ければ確認待ちに戻す
- 登録しないもの: 公式直販価格の確定（`official_registry` の証拠）・在庫・買取の取得の対象（商品ごとの固定の表）

## 4. 告知の登録（`register-event-candidate`）

- 前提: 告知の候補（`tcg-ann-`。自動で集めた正式なイベントは承認・登録しない）・APPROVED かつ承認で schedule・official_url を
  確かめた記録・`--official-page-checked`・公式の URL・抽選 / 予約（先着・再販は CSV の種類に無い）・運営者が渡した `+09:00` つきの
  受付開始 / 終了（終了 > 開始・終わっていない・1年以内）・商品名
- `data/tcg_verified_lotteries.csv` に1行（human_confirmed=true・verified_by は「operator（…）」・渡していない日程は空）。
  既存の読み込み（`manual._row_to_event`）で検査してから書く。同じ店・同じ開始で、同じ URL か正規化した商品名が同じ抽選
  （CSV・`exports/tcg/lotteries.json`）は重ねない。公式確認済みとして LP・抽選の通知の候補に入る（外部への送信はしない）
- 受付中かどうかは日程と今の時刻から決まる（登録で受付中にしない）

## 5. 表示・検査

- 運営者向け「新商品・新しいイベントの発見」: 確認待ち・承認済み（未登録）・登録済み・却下・STALE の件数（商品・告知）、
  候補の ID・状態（登録先の ID・却下の理由）、承認 → 見込み → 登録の CLI の手順。見るだけ（ボタン・フォームなし）
- CLI `discover` の Summary に approved / registered / rejected
- deploy-check #863: 承認済みの見込みが作れる・承認なし / 公式の確認なし / STALE / 古い / TCG / 第三者 / 部品番号なし / 色で
  価格が違う / 照合済み / 機種 + 容量の重複を登録しない・告知（日程なし・時差なし・公式の確認なし・再販・承認なし）を登録しない・
  CLI は見込みの後で書き main と照合する・登録の処理に commit / push が無い・CI は承認 / 登録しない・CI の生成コミットに正本
  （config/・CSV）が入らない・取り込みの衝突で台帳を上書きしない。正本と台帳の登録の対応は別の項目で warning（登録を戻した
  直後は次の discover まで食い違う。CI を止めない）
- CI の取り込みの衝突: 発見の台帳（人の判断が入る）は CI の側で上書きせずに止める（`daily_lp.yml`）

## 6. テスト

- tests/test_phase28_review.py（44件）。Apple は本物と同じ形の小さな HTML、正本は一時ファイル（本物の正本・CSV は不変を確認）
- mutation: 34/34（承認の迂回・STALE の登録 / 承認・機種 + 容量 / 部品番号 / ID / JAN の重複・dry-run で書く・自動 commit・時差なし /
  UTC / 終わった日程・公式ページの確認なし・再販の登録・TCG を正本へ・既存の商品を変えても書く・却下の理由・main と照合しない・
  台帳のほかの候補 / 対象の候補の価格の違いを許す・main の却下を無視・取得なしで照らし合わせない・正本を読めない日に全部戻す・
  正式なイベントの承認 / 登録・告知の重複・表記の揺れ・部品番号の推測・価格の確認なし・台帳の保存の失敗で正本を戻さない・
  CI の衝突で台帳を上書き・戻したときに一致の記録を残す・告知を開始日時で照らし合わせる・受付中の告知の注意なし）

## 7. レビュー・監査の指摘（対応済み）

- High（レビュー）: 承認で手元の台帳が main と変わるので、手順どおりの `--confirm` が必ず main との照合で止まった → 台帳は
  この候補の判断の項目だけの違いを許す（`ledgers_match_except`）
- High（レビュー）: 正本だけを戻すと、その機種のページを読むまで（最大3日・読めない機種は無期限）台帳が REGISTERED のまま
  #863 が error で CI が止まる → `discover` が取得に依らず照らし合わせる・対応の項目は warning
- Medium（レビュー）: `git revert` は CI の生成で変わる台帳で衝突する → 取り消しは正本の差分だけ（台帳は discover が戻す）
- Medium（レビュー）: 正式なイベント（MATCHED_EVENT）を承認・登録でき、自動で集めた抽選と手動の CSV に二重に入りえた → 承認
  できない・告知の候補だけ登録
- Medium（レビュー）: 発見の形の商品の判定が price_observed_on だけで、手で足した商品で CI が止まりえた → 対応の項目は warning
- Medium（監査）: CI の取り込みの衝突で、人の判断の入った台帳を CI の版で上書きした → 衝突したら止める
- Low: 台帳の保存の失敗で正本と台帳がずれる（正本を戻す）・JAN の重複・登録に要る証拠（part_numbers・capacity・
  official_price）・台帳に無い古い候補の却下の理由は省略可・push の手順の表示・照合で対象の候補の価格などの変化と main での
  却下 / 登録を見る・日程は +09:00 だけ・終わった / 1年より先の日程・正規化した商品名と自動で集めた抽選との重複・「通知しない」
  の表示を「外部には送信しない（LP・抽選の通知の候補には入る）」に・#863 で CI の生成コミットに正本が入らないこと
- Low（再監査）: 台帳の保存の OSError 以外の例外でも正本を戻す・受付が始まっている告知は dry-run で「登録すると直後から
  受付中・公式確認済みとして LP に出る」と注意
- High（再レビュー）: 登録を戻した後の照らし合わせが match_to_existing を残し、#862（確認待ちの一致）が error で CI を止めた
  → 確認待ちに戻すときに一致の記録も消す。Low: 告知の照らし合わせは店と URL で（延期で開始日時を直しても戻さない）・
  照合のエラー文に原因と「承認と登録は1件ずつ」・CI のログの衝突の一覧の改行

## 8. 既知の制約（Low・記録だけ）

- 同じ告知の URL で複数の商品を登録したとき、1行だけ CSV から外しても、台帳の候補は登録済みのまま（照らし合わせが「店|URL」の
  ため。CI は止めない。運用の文書に注意を書いた）
- 告知の registered_id は「店|URL|開始」。URL に「|」が入ると照らし合わせで確認待ちに戻る（安全側。公式の URL では起きない）

## 9. 本番の確認（2026-10-17）

- 最初の1件（canary）: ユーザーの承認の後、iPhone Air 256GB（候補 apple-24816e322cf0）を承認（official_url・part_numbers・
  capacity・official_price・colors を確認）→ dry-run → `--confirm` で `prod_iphoneair_256` を登録（コミット 9cb6caf1。正本と台帳の
  2ファイルだけ）。正本 45 → 46
- Daily LP の手動の実行（Run 39034279118・success・1時間13分）・生成コミット b37a1fe4（config/・CSV を含まない）
- 台帳: 登録した候補は REGISTERED のまま・同じ「機種 + 容量」の新しい候補は無し・照らし合わせで戻した候補 0。この実行の Apple は
  iphone-18-pro・iphone-17e を読んだ（iphone-air は次以降の実行で読み、正本と一致する。`canonical_iphones` は本番の正本で
  ("iphone air", "256GB") → prod_iphoneair_256 を返す）。新しく読んだ2機種で確認待ちの候補が増えた（Apple の候補 7 → 16）
- 利益: 利益ルート 0（利益0件の診断に「売却の候補なし」で入るだけ）・今すぐ行動できない（unverified_buy_price・no_sell_price）・
  公式の価格は設定値の参考（VERIFY_FROM_OFFICIAL）・在庫は作らない
- deploy-check エラー 0（#862・#863 の2項目とも OK）・prelaunch ❌ 0・Phase 24 の受入状態は PHASE24_WAITING・外部への送信 0
