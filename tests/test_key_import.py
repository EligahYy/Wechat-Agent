import hashlib
import hmac
import json
import struct
import tomllib
from pathlib import Path

import pytest

from wechat_agent.key_import import ImportError, import_legacy


@pytest.fixture
def legacy(tmp_path):
    root = tmp_path / "old"
    (root / "data").mkdir(parents=True)
    db = tmp_path / "xwechat_files/wxid_synthetic_1234/db_storage"
    raw = b"K" * 32
    for name in ("message/message_0.db", "contact/contact.db", "session/session.db"):
        p = db / name
        p.parent.mkdir(parents=True, exist_ok=True)
        page = bytearray(b"X" * 4096)
        page[:16] = b"S" * 16
        enc = hashlib.pbkdf2_hmac("sha512", raw, page[:16], 256000, 32)
        mac = hashlib.pbkdf2_hmac(
            "sha512", enc, bytes(x ^ 0x3A for x in page[:16]), 2, 32
        )
        page[-64:] = hmac.new(
            mac, page[16:4032] + struct.pack("<I", 1), hashlib.sha512
        ).digest()
        p.write_bytes(page)
    (root / "data/config.json").write_text(json.dumps({"db_dir": str(db)}))
    (root / "data/all_keys.json").write_text(
        json.dumps(
            {
                "_format": "wechat-export-macos/raw-key-v1",
                "_key_type": "account_raw_key",
                "_raw_key": raw.hex(),
                "_account_dir": str(db),
                "_wechat": {"version": "4.1.15"},
            }
        )
    )
    return root, db, raw


def test_preview_write_permissions_backup_preserve_and_idempotence(
    legacy, tmp_path, capsys
):
    root, db, raw = legacy
    target = tmp_path / "config/keys.toml"
    result = import_legacy(root, target)
    assert result["validated_databases"] == 3 and not target.exists()
    target.parent.mkdir()
    original = b'[accounts.other]\naccount_id="other"\ndata_key="existing-synthetic"\n'
    target.write_bytes(original)
    result = import_legacy(root, target, write=True)
    assert result["written"] and Path(result["backup"]).read_bytes() == original
    loaded = tomllib.loads(target.read_text())
    assert loaded["accounts"]["other"]["data_key"] == "existing-synthetic"
    assert loaded["accounts"]["wxid_synthetic_1234"]["data_key"] == raw.hex()
    assert target.stat().st_mode & 0o777 == 0o600
    before = target.read_bytes()
    assert import_legacy(root, target, True)["status"] == "already_present"
    assert before == target.read_bytes()
    assert (
        raw.hex() not in json.dumps(result) and raw.hex() not in capsys.readouterr().out
    )


def test_bad_page_does_not_write(legacy, tmp_path):
    root, db, raw = legacy
    page = db / "message/message_0.db"
    data = bytearray(page.read_bytes())
    data[25] ^= 1
    page.write_bytes(data)
    with pytest.raises(ImportError, match="首页校验失败"):
        import_legacy(root, tmp_path / "keys.toml", True)
    assert not (tmp_path / "keys.toml").exists()


def test_conflicting_key_never_overwritten(legacy, tmp_path):
    root, _, _ = legacy
    target = tmp_path / "keys.toml"
    old = b'[accounts.wxid_synthetic_1234]\ndata_key="do-not-overwrite"\n'
    target.write_bytes(old)
    with pytest.raises(ImportError, match="拒绝覆盖"):
        import_legacy(root, target, True)
    assert target.read_bytes() == old


def test_account_mismatch_rejected_without_leaking_key(legacy, tmp_path):
    root, db, raw = legacy
    p = root / "data/all_keys.json"
    d = json.loads(p.read_text())
    d["_account_dir"] = str(tmp_path / "another")
    p.write_text(json.dumps(d))
    with pytest.raises(ImportError) as e:
        import_legacy(root, tmp_path / "keys.toml", True)
    assert raw.hex() not in str(e.value)


def test_inline_empty_store_and_malformed_secret_safe(legacy, tmp_path):
    root, _, raw = legacy
    target = tmp_path / "keys.toml"
    target.write_text("accounts = {}\n")
    assert import_legacy(root, target, True)["written"]
    source = root / "data/all_keys.json"
    source.write_text('{"_raw_key":"' + raw.hex())
    with pytest.raises(ImportError) as exc:
        import_legacy(root, tmp_path / "new.toml", True)
    assert raw.hex() not in str(exc.value)
