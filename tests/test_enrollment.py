import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import pytest

from laptop_link_mcp import enrollment
from laptop_link_mcp.main import configuration


@contextmanager
def http_file(data, status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == '/client.key'
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('name', ['../escape', '/tmp/key', 'a/b', 'a\\b', '$(whoami)', '`id`', 'a;id',
                                  '-option', '.', '', 'a b', 'a\nkey', 'client.key', 'é', 'a'*65])
def test_invalid_key_names(name):
    with pytest.raises(ValueError):
        enrollment.key_filename(name)


@pytest.mark.parametrize(('address', 'port'), [('http://127.0.0.1', '8000'), ('127.0.0.1/evil', '8000'),
                                              ('127.0.0.1', '0'), ('127.0.0.1', '65536'),
                                              ('127.0.0.1', '8000;id'), ('0.0.0.0', '8000')])
def test_invalid_urls(address, port):
    with pytest.raises(ValueError):
        enrollment.server_url(address, port)


def test_download_permissions_default_and_no_overwrite(tmp_path, monkeypatch):
    directory = tmp_path / 'keys'
    key = bytes(range(32))
    with http_file(key) as port:
        saved = enrollment.download_key('127.0.0.1', port, 'office-mac_2', directory)
        assert saved.read_bytes() == key
        assert saved.stat().st_mode & 0o777 == 0o600
        assert directory.stat().st_mode & 0o777 == 0o700
        assert (directory / 'config.json').stat().st_mode & 0o777 == 0o600
        monkeypatch.setattr(enrollment, 'config_directory', lambda: directory)
        assert enrollment.default_key() == saved
        with pytest.raises(ValueError, match='already exists'):
            enrollment.download_key('127.0.0.1', port, 'office-mac_2', directory)
        assert saved.read_bytes() == key
    assert not list(directory.glob('.download-*'))


@pytest.mark.parametrize(('body', 'status'), [(b'bad', 200), (b'x'*33, 200), (b'x'*32, 404), (b'x'*32, 302)])
def test_bad_download_does_not_install_or_change_default(tmp_path, body, status):
    settings = tmp_path / 'config.json'
    settings.write_text('{"key":"/old/key"}')
    with http_file(body, status) as port:
        with pytest.raises(ValueError):
            enrollment.download_key('127.0.0.1', port, 'new-key', tmp_path)
    assert not (tmp_path / 'new-key.key').exists()
    assert json.loads(settings.read_text()) == {'key': '/old/key'}
    assert not list(tmp_path.glob('.download-*'))


def test_symlink_destination_not_followed(tmp_path):
    target = tmp_path / 'target'
    target.write_bytes(b'original')
    (tmp_path / 'client.key').symlink_to(target)
    with pytest.raises(ValueError):
        enrollment.download_key('127.0.0.1', '8000', 'client', tmp_path)
    assert target.read_bytes() == b'original'


def test_cli_uses_saved_key_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, 'config_directory', lambda: tmp_path)
    saved = tmp_path / 'saved.key'
    explicit = tmp_path / 'explicit.key'
    for path in [saved, explicit]:
        path.write_bytes(bytes(range(32)))
        path.chmod(0o600)
    enrollment.save_default_key(saved, tmp_path)
    bridge = tmp_path / 'bridge'
    bridge.touch(mode=0o700)
    monkeypatch.setattr('sys.argv', ['laptop-link-mcp', '--bridge', str(bridge)])
    assert configuration().key == saved
    monkeypatch.setattr('sys.argv', ['laptop-link-mcp', '--bridge', str(bridge), '--key', str(explicit)])
    assert configuration().key == explicit
    (tmp_path / 'config.json').unlink()
    assert configuration().key == explicit


def test_no_config_explains_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, 'config_directory', lambda: tmp_path)
    with pytest.raises(ValueError, match='Run scripts/setup.sh'):
        enrollment.default_key()


def test_config_failure_rolls_back_download(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError('Cannot save configuration')
    monkeypatch.setattr(enrollment, 'save_default_key', fail)
    with http_file(bytes(32)) as port:
        with pytest.raises(OSError, match='Cannot save'):
            enrollment.download_key('127.0.0.1', port, 'new-key', tmp_path)
    assert not (tmp_path / 'new-key.key').exists()
    assert not list(tmp_path.glob('.download-*'))
