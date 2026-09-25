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

if __name__ == '__main__':
    import argparse, hashlib, json, pathlib, subprocess, tarfile, tempfile
    from unittest.mock import patch
    from build import build, run, sha
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip',type=pathlib.Path,nargs='?')
    args=ap.parse_args()
    if args.zip:
        with tempfile.TemporaryDirectory(prefix='q2-package-') as tmp:
            root=pathlib.Path(tmp)
            custom=root/"custom ' logo.jpg"
            custom.write_bytes(logo)
            def change_source(*command):
                if command[0]=='mksquashfs': custom.write_bytes(b'edited during compression')
                return run(*command)
            a=root/"build ' a"; b=root/'build b'
            with patch('build.run',side_effect=change_source):
                build(args.zip,a,custom)
            build(args.zip,b,ROOT/'assets/logo.jpg')
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
