#!/usr/bin/env python3
"""Install the pinned source patch into project-local tools, preserving the old CLI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).rstrip('\n')


def prepare_checkout(destination, manifest, patch):
    if destination.is_symlink():
        raise ValueError('source_destination_is_symlink')
    payload = patch.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest['patch_sha256']:
        raise ValueError('patch_hash_mismatch')
    if not (destination / '.git').is_dir():
        if destination.exists():
            raise ValueError('source_destination_exists')
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--no-checkout', manifest['upstream'], str(destination)], check=True)
        subprocess.run(['git', '-C', str(destination), 'checkout', '--detach', manifest['base_commit']], check=True)
    if _git(destination, 'remote', 'get-url', 'origin') != manifest['upstream']:
        raise ValueError('source_origin_mismatch')
    if _git(destination, 'rev-parse', 'HEAD') != manifest['base_commit']:
        raise ValueError('source_base_mismatch')
    current = subprocess.check_output(['git', '-C', str(destination), 'diff', '--binary', 'HEAD'])
    untracked = _git(destination, 'ls-files', '--others', '--exclude-standard')
    if current == payload and not untracked:
        return
    if current or untracked or _git(destination, 'status', '--porcelain'):
        raise ValueError('source_checkout_modified')
    subprocess.run(['git', '-C', str(destination), 'apply', '--check', str(patch.resolve())], check=True)
    subprocess.run(['git', '-C', str(destination), 'apply', str(patch.resolve())], check=True)
    # Include newly created source files in subsequent integrity comparisons.
    subprocess.run(['git', '-C', str(destination), 'add', '--intent-to-add', '.'], check=True)
    if subprocess.check_output(['git', '-C', str(destination), 'diff', '--binary', 'HEAD']) != payload:
        raise ValueError('applied_patch_mismatch')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true', help='Verify/apply source without building or starting a service.')
    parser.add_argument('--transport', choices=('https', 'ssh'), default='https')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    patch_dir = root / 'patches/wx-cli'
    manifest = json.loads((patch_dir / 'manifest.json').read_text())
    if args.transport == 'ssh':
        manifest['upstream'] = 'git@github.com:pandorafuture/wx-cli.git'
    managed = root / '.local/tools/wx-cli' / manifest['version']
    source = managed / 'source'
    prepare_checkout(source, manifest, patch_dir / manifest['patch'])
    if args.prepare_only:
        print(source)
        return 0
    cargo = shutil.which('cargo')
    if cargo is None:
        raise ValueError('rust_toolchain_required: install Rust, then rerun this installer')
    subprocess.run([cargo, 'build', '--release', '--locked', '-p', 'wx-cli', '--bin', 'wx-cli'], cwd=source, check=True)
    target = Path(os.environ.get('CARGO_TARGET_DIR', str(source / 'target')))
    if not target.is_absolute():
        target = source / target
    built = target / 'release/wx-cli'
    version = subprocess.check_output([str(built), '--version'], text=True)
    if manifest['version'] not in version:
        raise ValueError('built_version_mismatch')
    destination = managed / 'bin/wx-cli'
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.installing')
    shutil.copy2(built, temporary)
    temporary.chmod(0o755)
    os.replace(temporary, destination)
    (managed / 'installed.json').write_text(json.dumps({
        'base_commit': manifest['base_commit'], 'patch_sha256': manifest['patch_sha256'],
        'binary_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
    }, indent=2) + '\n')
    print(destination)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'Installation stopped: {error}', file=sys.stderr)
        raise SystemExit(1)
