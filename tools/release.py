#!/usr/bin/env python3
"""Package both variants locally; optionally upload and publish one verified release."""
import argparse
import hashlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from build import ROOT, VERSIONS, ZIP_SHA, DEMO_SHA, build, check, run, sha, source_sha256

TAG = '3.3R'
ASSETS = {'normal': 'Q2.Firmware.V3.3.zip', 'compact': 'Q2.Firmware.V3.3-compact.zip'}
NOTES = '''- Compact: a single Return press on Now Playing goes back again. The stock hold-release latch is cleared on that page instead of swallowing the release and forcing a second press.
'''


def release_body(out, record):
    """Changelog bullets plus the SHA-256 block used by previous releases."""
    lines = [NOTES.rstrip(), '', 'SHA-256:']
    for variant, asset in ASSETS.items():
        lines.append(f'- {asset}: `{record["assets"][asset]}`')
        manifest = json.loads((out/variant/'manifest.json').read_text())
        lines.append(f'- update.tar ({manifest["version"]}): `{manifest["update_sha256"]}`')
    return '\n'.join(lines) + '\n'


def validate(directory, variant):
    m = json.loads((directory/'manifest.json').read_text())
    check(m['variant'] == variant and m['version'] == VERSIONS[variant], 'Wrong variant identity')
    check(m['source_sha256'] == source_sha256(), 'Stale release sources')
    check(m['input_zip_sha256'] == ZIP_SHA and m['stock_demo_sha256'] == DEMO_SHA, 'Wrong stock identity')
    for name, key in [('demo', 'demo_sha256'), ('stock-demo', 'stock_demo_sha256'),
                      ('patch.bin', 'patch_sha256'), ('rootfs.squashfs', 'rootfs_sha256'),
                      ('update.tar', 'update_sha256')]:
        check(sha((directory/name).read_bytes()) == m[key], f'{directory/name}: hash mismatch')
    with tarfile.open(directory/'update.tar') as t:
        check(t.getnames() == ['firmware_v20.info', 'recovery-update', 'recovery-update/xImage',
                               'recovery-update/rootfs.squashfs'], 'Unexpected update members')
        info = t.extractfile('firmware_v20.info').read().decode().splitlines()
        check(info[:2] == ['Shanling Q2', VERSIONS[variant]] and len(info) == 4, 'Wrong update identity')
        for line, name, key in zip(info[2:], ['recovery-update/xImage', 'recovery-update/rootfs.squashfs'],
                                  ['kernel_sha256', 'rootfs_sha256']):
            data = t.extractfile(name).read()
            check(line.split() == [hashlib.md5(data).hexdigest(), name] and sha(data) == m[key], 'Update payload mismatch')
    subprocess.run([sys.executable, str(ROOT/'tools/test_build.py'), '--build', str(directory)], check=True)
    subprocess.run([sys.executable, str(ROOT/'tools/test_patch.py'), str(directory)], check=True)


def archive_bytes(directory):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in ('update.tar', 'manifest.json'):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, (directory/name).read_bytes())
    return stream.getvalue()


def package(stock, out, logo):
    check(not out.exists(), 'Release output must be a fresh directory')
    out.mkdir(parents=True)
    source = source_sha256()
    revision = run('git', '-C', ROOT, 'rev-parse', 'HEAD').strip()
    checksums = {}
    for variant, asset in ASSETS.items():
        for suffix in ('', '-repeat'):
            build(stock, out/(variant+suffix), logo, compact=variant == 'compact')
            validate(out/(variant+suffix), variant)
        a, b = out/variant, out/(variant+'-repeat')
        check((a/'update.tar').read_bytes() == (b/'update.tar').read_bytes(), f'{variant}: non-reproducible update')
        data = archive_bytes(a)
        check(data == archive_bytes(b), f'{variant}: non-reproducible ZIP')
        (out/asset).write_bytes(data)
        checksums[asset] = sha(data)
    check(source == source_sha256() and revision == run('git', '-C', ROOT, 'rev-parse', 'HEAD').strip(),
          'Source changed during release build')
    record = dict(tag=TAG, revision=revision, source_sha256=source, assets=checksums)
    (out/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in checksums.items()))
    (out/'release-notes.md').write_text(release_body(out, record))
    (out/'release.json').write_text(json.dumps(record, indent=2)+'\n')
    print(f'Both variants validated and reproducible: {out}')


def upload(out, repo, publish=False):
    record = json.loads((out/'release.json').read_text())
    check(record['tag'] == TAG and record['source_sha256'] == source_sha256(), 'Wrong release source/tag')
    check(set(record['assets']) == set(ASSETS.values()), 'Both variants are required')
    for variant, asset in ASSETS.items():
        validate(out/variant, variant)
        data = (out/asset).read_bytes()
        check(sha(data) == record['assets'][asset] and data == archive_bytes(out/variant), 'Release ZIP mismatch')
    sums = ''.join(f'{record["assets"][name]}  {name}\n' for name in ASSETS.values())
    check((out/'SHA256SUMS').read_text() == sums, 'Release checksums mismatch')
    (out/'release-notes.md').write_text(release_body(out, record))
    gh = ['gh', '--repo', repo, 'release']
    # Listing distinguishes an absent tag from an authentication/network failure.
    releases = json.loads(run(*gh, 'list', '--limit', '1000', '--json', 'tagName,isDraft'))
    existing = next((r for r in releases if r['tagName'] == TAG), None)
    if existing:
        check(existing['isDraft'], 'Refusing to overwrite a published release')
        run(*gh, 'edit', TAG, '--draft', '--title', TAG, '--notes-file', out/'release-notes.md')
    else:
        run(*gh, 'create', TAG, '--draft', '--target', record['revision'], '--title', TAG,
            '--notes-file', out/'release-notes.md')
    files = list(ASSETS.values())
    run(*gh, 'upload', TAG, *(out/name for name in files), '--clobber')
    with tempfile.TemporaryDirectory(prefix='q2-release-verify-') as tmp:
        run(*gh, 'download', TAG, '--dir', tmp)
        for name in files:
            check((pathlib.Path(tmp)/name).read_bytes() == (out/name).read_bytes(), f'Remote asset mismatch: {name}')
    if publish:
        run(*gh, 'edit', TAG, '--draft=false')
    print(f'{"Published" if publish else "Verified draft"}: https://github.com/{repo}/releases/tag/{TAG}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    p = commands.add_parser('package')
    p.add_argument('zip', type=pathlib.Path)
    p.add_argument('--out', type=pathlib.Path, required=True)
    p.add_argument('--logo', type=pathlib.Path, default=ROOT/'assets/logo.jpg')
    p = commands.add_parser('upload')
    p.add_argument('out', type=pathlib.Path)
    p.add_argument('--repo', default='DiamondBond/q2-ringnav')
    p.add_argument('--publish', action='store_true')
    a = ap.parse_args()
    try:
        # Validation runs the MIPS suite, so fail before four builds, not after them.
        check(importlib.util.find_spec('unicorn') is not None,
              'Release validation needs the requirements.txt environment: pip install -r requirements.txt')
        if a.command == 'package':
            package(a.zip, a.out.resolve(), a.logo)
        else:
            upload(a.out.resolve(), a.repo, a.publish)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        ap.error(str(exc))
