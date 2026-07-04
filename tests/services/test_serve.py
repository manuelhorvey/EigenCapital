from pathlib import Path

from paper_trading.api import common


class FakeResponse:
    def __init__(self):
        self.status = None
        self.headers = []
        self.body = bytearray()
        self.wfile = self

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers.append((name, value))

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data)


def test_try_serve_file_rejects_asset_path_traversal(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(common, "DASHBOARD_DIST", str(root))
    monkeypatch.setattr(common, "FRONTEND_DIR", str(root))

    resp = FakeResponse()

    assert common.try_serve_file("/assets/../secret.txt", resp) is False
    assert resp.body == b""


def test_try_serve_file_serves_files_within_static_root(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    asset_dir = root / "assets"
    asset_dir.mkdir(parents=True)
    asset = asset_dir / "app.js"
    asset.write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(common, "DASHBOARD_DIST", str(root))
    monkeypatch.setattr(common, "FRONTEND_DIR", str(Path(tmp_path) / "frontend"))

    resp = FakeResponse()

    assert common.try_serve_file("/assets/app.js", resp) is True
    assert resp.status == 200
    assert bytes(resp.body) == b"console.log('ok')"
