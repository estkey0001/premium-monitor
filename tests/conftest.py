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


class _AllowAllRobots:
    """テスト用の robots.txt 判定（ネットワークに出ない。すべて許可・Crawl-delay なし）。"""

    def is_allowed(self, url):
        return True

    def get_crawl_delay(self, url):
        return None


@pytest.fixture(autouse=True)
def _no_network_polite_fetch(request, monkeypatch):
    """取得の共通の作法（src/collectors/polite.py）が、テスト中に robots.txt を取りに行ったり60秒待ったりしないようにする。

    robots.txt・間隔の判定そのものを確かめるテストは `@pytest.mark.real_polite` を付けて、この差し替えを外す
    （そのテストの中で偽の robots.txt・時計を渡す）。
    """
    if request.node.get_closest_marker("real_polite"):
        yield
        return
    from src.collectors import polite
    # RateLimiter そのものは差し替えない（RateLimiter の60秒を確かめる既存のテストがある）
    monkeypatch.setattr(polite, "robots_checker", lambda: _AllowAllRobots())
    monkeypatch.setattr(polite, "polite_wait", lambda url, source_id="": 0.0)
    yield


def pytest_configure(config):
    config.addinivalue_line("markers", "real_polite: 買取の取得の robots.txt・間隔の判定を差し替えずに確かめるテスト")
