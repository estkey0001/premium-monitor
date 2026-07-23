"""SaaS 基盤モジュール（サービス層のみ・AIロジックは変更しない）。

構成:
  subscription.py  Free/Pro/Enterprise 権限ゲート
  accounts.py      account_id 単位の口座・設定・Watchlist・Portfolio ストア
  auth.py          認証プロバイダ抽象（email/google/apple・env gated・実OAuthは外部基盤で）
  billing.py       Stripe プラン定義・webフック抽象（env gated・キーは埋め込まない）
  api.py           REST API（標準ライブラリ http.server・追加依存なしで起動可）
"""
