"""テスト全体の共通設定。"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _diagnostics_to_tmp(tmp_path_factory):
    """LP の生成を伴うテストで、利益商品の内部診断を一時フォルダに書く（exports/ の実データを上書きしない）。

    module / class 単位の fixture で LP を生成するテストもあるので、セッションの最初に設定する。
    """
    old = os.environ.get("OPPORTUNITY_DIAGNOSTICS_DIR")
    os.environ["OPPORTUNITY_DIAGNOSTICS_DIR"] = str(tmp_path_factory.mktemp("opportunity_diagnostics"))
    yield
    if old is None:
        os.environ.pop("OPPORTUNITY_DIAGNOSTICS_DIR", None)
    else:
        os.environ["OPPORTUNITY_DIAGNOSTICS_DIR"] = old
