#!/usr/bin/env python3
"""JPEG checks; optionally pass the stock ZIP to test packaging and reproducibility too."""
from build import ROOT, jpeg_size

logo = (ROOT/'assets/logo.jpg').read_bytes()
assert jpeg_size(logo) == (320, 375)
# JPEG permits extra FF fill bytes before a marker.
assert jpeg_size(logo[:2] + b'\xff' + logo[2:]) == (320, 375)
frame = b'\xff\xd8\xff\xc0\x00\x11\x08\x01\x77\x01\x40'
# The stock display_logo reads three bytes per pixel without converting grayscale/CMYK.
# It also requires the documented 8-bit baseline format.
def sof(marker=0xc0, precision=8, components=3):
    return (b'\xff\xd8\xff' + bytes([marker]) + (8+3*components).to_bytes(2,'big') +
            bytes([precision]) + b'\x01\x77\x01\x40' + bytes([components]) +
            b''.join(bytes([i+1,0x11,0]) for i in range(components)))
assert jpeg_size(sof()) == (320,375)
for data in (b'', b'not a JPEG', frame, frame + bytes(8),
             b'\xff\xd8\xff', b'\xff\xd8\xff\xe0\x00',
             b'\xff\xd8\xff\xe0\x00\x01', b'\xff\xd8\xff\xd9' + logo[2:],
             sof(components=1), sof(components=4), sof(precision=12),
             sof(marker=0xc2), sof(marker=0xc3)):
    try:
        jpeg_size(data)
    except ValueError:
        continue
    raise AssertionError(f'Accepted malformed JPEG header: {data!r}')
print('JPEG header regression checks passed.')

def validate_assets(directory):
    import json, subprocess
    from build import sha, run, fileoff, symbols
    from compact import AUDIT, BOTTOM, PITCH, decode, patch_asset, patch_code
    manifest = json.loads((directory/'manifest.json').read_text())
    compact = manifest['variant'] == 'compact'
    stock = (directory/'stock-demo').read_bytes()
    demo = (directory/'demo').read_bytes()
    # All original executable bytes outside the reviewed hooks, version and compact sites
    # must remain stock; the payload and ELF mapping are independently hashed by the runner.
    for group in [*AUDIT['immediates'], AUDIT['row_layout_calls'],
                  {'sites': [('0x522410', '0x0320f809')]}]:
        for address, _ in group['sites']:
            off = fileoff(stock, int(address, 16))
            if not compact:
                assert demo[off:off+4] == stock[off:off+4]
    assert manifest['version'].encode()+b'\0' in demo
    changed = manifest['changed_assets']
    assert set(changed) == ({'release/assets/default/raw/ui/'+p for p in AUDIT['assets']} if compact else set())
    def read(image, rel):
        return subprocess.check_output(['unsquashfs', '-cat', str(directory/image), rel])
    # Include every excluded UI screen and saved-preference defaults in byte parity checks.
    paths = [l.removeprefix('squashfs-root/') for l in run('unsquashfs', '-l', directory/'stock.squashfs').splitlines()
             if '/raw/ui/' in l and l.endswith('.bin') or l.endswith('/config.ini')]
    for rel in paths:
        original, new = read('stock.squashfs', rel), read('rootfs.squashfs', rel)
        if rel not in changed:
            assert new == original, rel
            continue
        short = rel.split('/raw/ui/')[1]
        assert new == patch_asset(short, original), short
        assert changed[rel] == dict(original_sha256=sha(original), sha256=sha(new))
        root = decode(new)
        nav = next(n for n in root[3] if n[2].get('name') == 'view_navbar')
        assert nav[2]['visible'] == 'false' and nav[2]['enable'] == 'false'
        def walk(n):
            yield n
            for child in n[3]: yield from walk(child)
        old_nodes, new_nodes = list(walk(decode(original))), list(walk(root))
        assert len(old_nodes) == len(new_nodes)
        for old, node in zip(old_nodes, new_nodes):
            for key, value in old[2].items():
                if 'font' in key or key == 'style': assert node[2][key] == value
        if short in ('folder_page.bin', 'localmusic_page.bin', 'localmusic/localclass_page.bin', 'localmusic/playlist_page.bin'):
            surface = next(n for n in root[3] if n[0] in ('list_view', 'table_view'))
            assert surface[1][1:] == [0, 375, BOTTOM], 'Lists must fill the client area'
            assert 4*PITCH <= BOTTOM, 'Four complete rows must fit'
        # Corrupt inputs must be rejected, never silently patched.
        try: patch_asset(short, original[:-1]+b'x')
        except ValueError: pass
        else: raise AssertionError('Accepted a changed asset')
    if compact:
        payload_symbols = symbols(directory/'patch.elf')
        for address in [AUDIT['immediates'][0]['sites'][0][0], '0x522410',
                        *(a for a, _ in AUDIT['row_layout_calls']['sites'])]:
            damaged = bytearray(stock)
            damaged[fileoff(stock, int(address, 16))] ^= 1
            try: patch_code(damaged, fileoff, payload_symbols)
            except ValueError: pass
            else: raise AssertionError(f'Accepted a changed instruction at {address}')
    print(f'{manifest["variant"]}: asset geometry, exclusion parity and mismatch rejection passed.')

if __name__ == '__main__':
    import argparse, hashlib, json, pathlib, subprocess, tarfile, tempfile
    from unittest.mock import patch
    from build import build, run, sha
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip',type=pathlib.Path,nargs='?')
    ap.add_argument('--build', type=pathlib.Path)
    args=ap.parse_args()
    if args.build: validate_assets(args.build)
    if args.zip:
        for compact in (False, True):
          with tempfile.TemporaryDirectory(prefix='q2-package-') as tmp:
              root=pathlib.Path(tmp)
              custom=root/"custom ' logo.jpg"
              custom.write_bytes(logo)
              def change_source(*command):
                  if command[0]=='mksquashfs': custom.write_bytes(b'edited during compression')
                  return run(*command)
              a=root/"build ' a"; b=root/'build b'
              with patch('build.run',side_effect=change_source):
                  build(args.zip,a,custom,compact)
              build(args.zip,b,ROOT/'assets/logo.jpg',compact)
              validate_assets(a)
              assert (a/'update.tar').read_bytes()==(b/'update.tar').read_bytes()
              manifest=json.loads((a/'manifest.json').read_text())
              assert manifest['logo_sha256']==sha(logo)
              for rel,expected in [('release/assets/default/raw/images/xx/logo.jpg',logo),
                                   ('release/bin/demo',(a/'demo').read_bytes())]:
                  assert subprocess.check_output(['unsquashfs','-cat',str(a/'rootfs.squashfs'),rel])==expected
              with tarfile.open(a/'update.tar') as archive:
                  info=archive.extractfile('firmware_v20.info').read().decode().splitlines()
                  assert info[:2]==['Shanling Q2',manifest['version']]
                  for line in info[2:]:
                      digest,name=line.split()
                      data=archive.extractfile(name).read()
                      assert hashlib.md5(data).hexdigest()==digest
                      if name.endswith('xImage'): assert sha(data)==manifest['kernel_sha256']
              print('Packaging, mutable logo, quoted paths and reproducibility checks passed.')
