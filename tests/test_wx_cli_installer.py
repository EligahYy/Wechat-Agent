"""The source installer applies a fixed patch without resetting user changes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


def installer():
    path = Path(__file__).parents[1] / 'scripts/install-wx-cli.py'
    spec = importlib.util.spec_from_file_location('wx_installer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


@pytest.fixture
def source_patch(tmp_path):
    source = tmp_path / 'upstream'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    git(source, 'config', 'user.email', 'test@example.invalid')
    git(source, 'config', 'user.name', 'Fixture')
    (source / 'main.rs').write_text('original\n')
    git(source, 'add', '.')
    git(source, 'commit', '-qm', 'base')
    commit = git(source, 'rev-parse', 'HEAD')
    (source / 'main.rs').write_text('fixed\n')
    patch = tmp_path / 'fix.patch'
    patch.write_text(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary'], text=True))
    git(source, 'restore', 'main.rs')
    manifest = {'upstream': str(source), 'base_commit': commit, 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest()}
    return source, patch, manifest


def test_installer_applies_fixed_patch_and_is_repeatable(tmp_path, source_patch):
    _, patch, manifest = source_patch
    module = installer()
    dest = tmp_path / 'managed source'
    module.prepare_checkout(dest, manifest, patch)
    assert (dest / 'main.rs').read_text() == 'fixed\n'
    module.prepare_checkout(dest, manifest, patch)
    assert (dest / 'main.rs').read_text() == 'fixed\n'
    assert git(dest, 'rev-parse', 'HEAD') == manifest['base_commit']


def test_installer_refuses_extra_changes_without_reset(tmp_path, source_patch):
    _, patch, manifest = source_patch
    module = installer()
    dest = tmp_path / 'managed'
    module.prepare_checkout(dest, manifest, patch)
    (dest / 'main.rs').write_text('user change\n')
    with pytest.raises(ValueError, match='source_checkout_modified'):
        module.prepare_checkout(dest, manifest, patch)
    assert (dest / 'main.rs').read_text() == 'user change\n'


def test_installer_rejects_patch_hash_mismatch_before_clone(tmp_path, source_patch):
    _, patch, manifest = source_patch
    module = installer()
    patch.write_text('tampered\n')
    dest = tmp_path / 'managed'
    with pytest.raises(ValueError, match='patch_hash_mismatch'):
        module.prepare_checkout(dest, manifest, patch)
    assert not dest.exists()


def test_installer_refuses_symlink_to_another_checkout(tmp_path, source_patch):
    source, patch, manifest = source_patch
    module = installer()
    destination = tmp_path / 'managed-link'
    destination.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match='source_destination_is_symlink'):
        module.prepare_checkout(destination, manifest, patch)
    assert (source / 'main.rs').read_text() == 'original\n'
