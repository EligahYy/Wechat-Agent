from fastapi.testclient import TestClient

from wechat_agent.api.app import create_app
from wechat_agent.config import Settings
from wechat_agent.services import Services


def test_built_frontend_is_same_origin_and_does_not_replace_api_or_expose_test_reset(tmp_path):
    folder=tmp_path/'frontend-dist'
    (folder/'assets').mkdir(parents=True)
    (folder/'index.html').write_text('<!doctype html><title>Desktop app</title>')
    (folder/'assets'/'app.js').write_text('console.log("built asset")')
    with TestClient(create_app(Settings(data_dir=tmp_path/'data',frontend_dir=folder),Services(auto_run=False))) as client:
        assert 'Desktop app' in client.get('/').text
        assert client.get('/assets/app.js').status_code==200
        assert client.get('/api/health').json()['status']=='ok'
        assert client.get('/api/does-not-exist').status_code==404
        assert client.post('/api/__test__/reset').status_code in {404,405}
        assert client.get('/../archive.sqlite3').status_code==404


def test_missing_frontend_build_keeps_api_available(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path/'data',frontend_dir=tmp_path/'missing'),Services(auto_run=False))) as client:
        assert client.get('/').status_code==404
        assert client.get('/api/health').status_code==200
