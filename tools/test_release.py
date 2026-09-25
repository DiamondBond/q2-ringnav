#!/usr/bin/env python3
"""Release failure paths without network access or proprietary firmware."""
import json
import pathlib
import subprocess
import tempfile
from unittest.mock import patch
import release

with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp)/'package'
    def fail_compact(stock, directory, logo, compact=False):
        if compact:
            raise ValueError('simulated compact build failure')
        directory.mkdir()
        (directory/'update.tar').write_bytes(b'normal')
        (directory/'manifest.json').write_text('{}')
    with patch('release.build', side_effect=fail_compact), patch('release.validate'), patch('release.run', return_value='revision'):
        try:
            release.package(pathlib.Path('stock.zip'), out, pathlib.Path('logo.jpg'))
        except ValueError as e:
            assert 'compact build failure' in str(e)
        else:
            raise AssertionError('Accepted a failed variant')
    assert not (out/'release.json').exists()
    assets = {}
    for variant, name in release.ASSETS.items():
        d = out/variant
        d.mkdir(exist_ok=True)
        (d/'update.tar').write_bytes(variant.encode())
        (d/'manifest.json').write_text(json.dumps(dict(
            variant=variant, version=release.VERSIONS[variant], update_sha256=release.sha(variant.encode()))))
        data = release.archive_bytes(d)
        (out/name).write_bytes(data)
        assets[name] = release.sha(data)
    record = dict(tag=release.TAG, revision='revision', source_sha256=release.source_sha256(), assets=assets)
    (out/'release.json').write_text(json.dumps(record))
    (out/'release-notes.md').write_text(release.release_body(out, record))
    (out/'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k, v in assets.items()))
    accepted = out/'accepted.json'
    accepted.write_text(json.dumps(dict(assets=assets, checks={v: dict.fromkeys(release.DEVICE_CHECKS, True) for v in release.ASSETS})))
    for failure in ('upload', 'download', 'corrupt', None):
        calls = []
        def gh(*args):
            calls.append(args)
            command = args[4]
            if command == 'list': return '[]'
            if command == failure:
                raise subprocess.CalledProcessError(1, args)
            if command == 'download':
                target = pathlib.Path(args[-1])
                for name in assets:
                    (target/name).write_bytes((out/name).read_bytes() if failure != 'corrupt' else b'bad')
            return ''
        with patch('release.validate'), patch('release.run', side_effect=gh):
            try:
                release.upload(out, 'owner/repo', True, accepted)
            except (ValueError, subprocess.CalledProcessError):
                assert failure
            else:
                assert failure is None
        assert any('--draft=false' in c for c in calls) == (failure is None)
    # Missing compact and unaccepted device checks must fail before contacting GitHub.
    (out/release.ASSETS['compact']).unlink()
    with patch('release.validate'), patch('release.run') as gh:
        try: release.upload(out, 'owner/repo')
        except OSError: pass
        else: raise AssertionError('Accepted a missing variant')
        gh.assert_not_called()
print('Dual-variant build/upload failure checks passed.')
