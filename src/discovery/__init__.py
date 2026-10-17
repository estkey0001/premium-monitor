"""新商品・新しいイベントの発見（Phase 27）。発見と正本（config/products.yaml・products の表）の登録を分ける。

発見 → 候補（PENDING_REVIEW / REVIEW_REQUIRED）→ 人の確認（APPROVED / REJECTED）→ 正本の登録は人が手で行う。
このパッケージは正本に書き込まない（products.yaml・products の表・official_registry を変えない）。
"""
