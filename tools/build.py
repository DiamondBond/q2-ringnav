#!/usr/bin/env python3
"""Reproducibly patch only the audited Q2 V1.32 ZIP. Requires LLVM and squashfs-tools.

--logo swaps the boot splash JPEG (320x375); it defaults to assets/logo.jpg.
"""
import argparse, hashlib, io, json, pathlib, re, struct, subprocess, tarfile, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
ZIP_SHA = '154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00'
DEMO_SHA = '2c5f06142850b4fc168f82b44a81550cce0a5b4b9fe1c179dced4a08a3049138'
VERSION = 'V2.7R'
BASE = 0xb00000
SCRATCH = 0xb0f000
RING_STEP = 48
HOOK = 0x4e85c8
HOOKS = {
    'on_wm_keyup_before_fun': (HOOK, 'ringnav'),
    'on_wm_tsdown_before_fun': (0x4e8bd0, 'ringnav_touch'),
    'widget_on_paint_border': (0x6596a0, 'ringnav_paint'),
    'widget_dispatch': (0x65e0ec, 'ringnav_dispatch'),
}

def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True)
def sha(b): return hashlib.sha256(b).hexdigest()

def source_sha256():
    """Hash every build input, so a test run cannot silently use a stale output directory."""
    h = hashlib.sha256()
    for rel in ['assets/logo.jpg', 'patch/contexts.inc', 'patch/link.ld', 'patch/offsets.inc',
                'patch/ringnav.c', 'patch/trampoline.S', 'tools/build.py']:
        h.update(rel.encode() + b'\0')
        h.update((ROOT/rel).read_bytes())
    return h.hexdigest()

def check(condition, message):
    if not condition: raise ValueError(message)
def jpeg_size(b):
    """Validate the splash's supported JPEG frame header and return its dimensions."""
    check(b[:2] == b'\xff\xd8', 'Logo must be a JPEG')
    i = 2
    while i < len(b):
        check(b[i] == 0xFF, 'Malformed JPEG')
        while i < len(b) and b[i] == 0xFF: i += 1
        check(i < len(b), 'Truncated JPEG marker')
        marker = b[i]
        i += 1
        if marker in (0xD9, 0xDA): break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7: continue
        check(marker not in (0, 0xD8), 'Malformed JPEG marker')
        check(i + 2 <= len(b), 'Truncated JPEG segment')
        size = struct.unpack_from('>H', b, i)[0]
        check(size >= 2 and i + size <= len(b), 'Invalid JPEG segment length')
        if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):
            check(size >= 8 and size == 8 + 3 * b[i+7], 'Invalid JPEG frame length')
            # Stock display_logo indexes decoded pixels as RGB triples (0x400ec0 onward),
            # but leaves libjpeg's output color space unchanged. Grayscale/CMYK are unsafe.
            check(marker == 0xC0 and b[i+2] == 8 and b[i+7] == 3,
                  'Logo must be an 8-bit, three-component baseline JPEG (not grayscale/CMYK)')
            h, w = struct.unpack_from('>HH', b, i+3)
            check(w > 0 and h > 0, 'Invalid JPEG dimensions')
            return w, h
        i += size
    raise ValueError('No JPEG size marker')
def symbols(p):
    out = {}
    for line in run('readelf', '-Ws', p).splitlines():
        s = line.split()
        if len(s) >= 8 and s[0].endswith(':'):
            try: out[s[7]] = int(s[1], 16)
            except ValueError: pass
    return out

def segments(b):
    phoff = struct.unpack_from('<I', b, 28)[0]
    size, num = struct.unpack_from('<HH', b, 42)
    check(size == 32, 'Unexpected ELF program header size')
    return [(phoff+i*size, struct.unpack_from('<8I', b, phoff+i*size)) for i in range(num)]
def fileoff(b, a):
    for _, (t, o, v, _, f, _, _, _) in segments(b):
        if t == 1 and v <= a < v+f: return o+a-v
    raise ValueError(f'Unmapped address {a:x}')

FUNCTIONS = {
 'window_manager': ('void *', 'void'),
 'window_manager_get_top_window': ('void *', 'void *'),
 'window_manager_is_animating': ('int', 'void *'),
 'window_manager_get_pointer_pressed': ('int', 'void *'),
 'widget_get_visible': ('int', 'void *'),
 'widget_get_prop_bool': ('int', 'void *, const char *, int'),
 'widget_get_prop_int': ('int', 'void *, const char *, int'),
 'widget_get_prop_str': ('const char *', 'void *, const char *, const char *'),
 'widget_get_text': ('const unsigned *', 'void *'),
 'widget_get_type': ('const char *', 'void *'),
 'widget_count_children': ('unsigned', 'void *'),
 'widget_get_child': ('void *', 'void *, unsigned'),
 'widget_set_prop_int': ('int', 'void *, const char *, int'),
 'widget_invalidate_force': ('int', 'void *, void *'),
 'widget_animator_start': ('int', 'void *'),
 'widget_animator_scroll_set_params': ('int', 'void *, int, int, int, int'),
 'slide_menu_set_value': ('int', 'void *, int'),
 'slide_menu_item_width': ('int', 'void *'),
 'slide_menu_on_scroll_done': ('int', 'void *, void *'),
 'widget_animator_scroll_create': ('void *', 'void *, unsigned, unsigned, int'),
 'widget_animator_on': ('unsigned', 'void *, unsigned, int (*)(void *, void *), void *'),
 'widget_set_focused': ('int', 'void *, int'),
 'widget_animator_pause': ('int', 'void *'),
 'widget_animator_destroy': ('int', 'void *'),
 'canvas_get_clip_rect': ('int', 'void *, void *'),
 'canvas_set_clip_rect': ('int', 'void *, const void *'),
 'canvas_set_fill_color': ('int', 'void *, unsigned'),
 'canvas_set_stroke_color': ('int', 'void *, unsigned'),
 'canvas_stroke_rect': ('int', 'void *, int, int, int, int'),
 'canvas_fill_rounded_rect': ('int', 'void *, const void *, const void *, const void *, unsigned'),
 'canvas_stroke_rounded_rect': ('int', 'void *, const void *, const void *, const void *, unsigned, unsigned'),
 'pointer_event_init': ('void *', 'void *, int, void *, int, int'),
 'time_now_ms': ('unsigned', 'void'),
 'timer_add': ('unsigned', 'int (*)(const void *), void *, unsigned'),
 'timer_remove': ('int', 'unsigned'),
 'tk_strcmp': ('int', 'const char *, const char *'),
 'slide_menu_scroll_to_next': ('int', 'void *'),
 'slide_menu_scroll_to_prev': ('int', 'void *'),
 'table_client_stop_animator_scroll': ('int', 'void *'),
 'table_client_set_yoffset': ('int', 'void *, int'),
 'scroll_view_set_offset': ('int', 'void *, int, int'),
 'table_client_scroll_to': ('int', 'void *, int'),
 'scroll_view_scroll_delta_to': ('int', 'void *, int, int, int'),
}
# Local stock routines in the SHA-256-pinned V1.32 executable.
PRIVATE_FUNCTIONS = {
    "slide_menu_item_width": 0x5f3040,
    "slide_menu_on_scroll_done": 0x5f3654,
}
GLOBALS = ['g_backlight_status', 'g_lockscreen_pageflag', 'g_testmode_flag',
           'g_guideflag', 'g_poweroff_state', 'g_usblink_status', 'bt__recv_pageflag',
           'g_power_longkey', 'g_ingore_bootkey_flag']
# Audited stock browsing state (not playback state); sizes are checked against the ELF.
CONTEXT_DATA = {'g_folder_path': 1024, 'g_class_type': 4,
                'g_local_classinfo_save': 912, 'g_artist_type': 4, 'album_modetype': 4}

FLAGS = ['--target=mipsel-linux-gnu','-march=mips32r2','-mabi=32','-mfp64',
         '-mno-abicalls','-fno-pic','-G0','-ffreestanding','-fno-builtin',
         '-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
         '-Os','-Wall','-Wextra','-Werror']

def compile_payload(out):
    """Compile and link the payload."""
    run('clang',*FLAGS,'-I',out,'-c',ROOT/'patch/ringnav.c','-o',out/'ringnav.o')
    run('clang',*FLAGS,'-c',ROOT/'patch/trampoline.S','-o',out/'trampoline.o')
    run('ld.lld','-m','elf32ltsmip','-T',ROOT/'patch/link.ld','-e','ringnav',
        out/'ringnav.o',out/'trampoline.o','-o',out/'patch.elf')
    run('llvm-objcopy','-O','binary',out/'patch.elf',out/'patch.bin')
    return symbols(out/'patch.elf')

def build(zip_path, out, logo):
    out.mkdir(parents=True, exist_ok=True)
    check(not (out/'update.tar').exists(), 'Output already exists; use a fresh --out directory')
    source = source_sha256()
    raw = zip_path.read_bytes()
    check(sha(raw) == ZIP_SHA, 'Unsupported ZIP: SHA-256 differs from audited original')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        tarbytes = z.read('Q2 Firmware V1.32/update.tar')
    with tarfile.open(fileobj=io.BytesIO(tarbytes)) as t:
        meta = t.getmembers()
        check([m.name for m in meta] == ['firmware_v20.info','recovery-update',
              'recovery-update/xImage','recovery-update/rootfs.squashfs'], 'Unexpected package members')
        blobs = {m.name:t.extractfile(m).read() for m in meta if m.isfile()}
    info = blobs['firmware_v20.info'].decode().splitlines()
    check(info[:2] == ['Shanling Q2','V1.32'], 'Wrong model/version')
    for line in info[2:]:
        digest, name = line.split()
        check(hashlib.md5(blobs[name]).hexdigest() == digest, 'Stock MD5 mismatch')
    sq = out/'stock.squashfs'; sq.write_bytes(blobs['recovery-update/rootfs.squashfs'])
    raw_demo = subprocess.check_output(['unsquashfs','-cat',str(sq),'release/bin/demo'])
    check(sha(raw_demo) == DEMO_SHA, 'Unsupported demo binary')
    # Every allowlisted context must be a window name. The runtime name is the root "name"
    # property of the UI asset, not the asset path, so check the stock rootfs assets directly:
    # a prefix-trimmed typo cannot silently disable a screen this way.
    contexts = re.findall(r'"([^"]+)"', (ROOT/'patch/contexts.inc').read_text())
    check(contexts, 'No navigation contexts audited')
    windows = set()
    for line in run('unsquashfs', '-l', sq).splitlines():
        found = re.search(r'/raw/ui/(.+)\.bin$', line)
        if not found: continue
        rel = found.group(1)
        data = subprocess.check_output(['unsquashfs', '-cat', str(sq),
                                        'release/assets/default/raw/ui/'+rel+'.bin'])
        i = data.find(b'name\x00')
        name = data[i+5:data.find(b'\x00', i+5)].decode('utf-8', 'replace') if i >= 0 else ''
        windows.add(name or rel.split('/')[-1])
    check(windows, 'No UI assets in the stock rootfs')
    for name in contexts:
        check(name in windows, f'Context {name} is not a window name in the stock rootfs')
    demo = out/'stock-demo'; demo.write_bytes(raw_demo)
    syms = symbols(demo)
    syms.update(PRIVATE_FUNCTIONS)
    header = [f'#define RING_STEP {RING_STEP}']
    for name in ('keyup', 'touch', 'paint', 'dispatch'):
        header += [f'extern int stock_{name}_trampoline(void *, void *);',
                   f'#define stock_{name} stock_{name}_trampoline']
    for name,(ret,args) in FUNCTIONS.items():
        header.append(f'#define {name} (({ret} (*)({args}))0x{syms[name]:x}u)')
    for name in GLOBALS:
        header.append(f'#define {name} (*(volatile unsigned char *)0x{syms[name]:x}u)')
    symbol_table = run('readelf', '-Ws', demo)
    for name, size in CONTEXT_DATA.items():
        check(re.search(rf'\b{size}\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+{name}$',
                        symbol_table, re.M), f'{name}: context data size mismatch')
        header.append(f'#define {name} ((const unsigned char *)0x{syms[name]:x}u)')
    (out/'stock.h').write_text('\n'.join(header)+'\n')
    ps = compile_payload(out)
    payload = (out/'patch.bin').read_bytes()
    check(len(payload) < SCRATCH-BASE, 'Payload overlaps its scratch page')
    check(ps['__scratch_start'] == SCRATCH, 'Scratch state moved')
    check(ps['__scratch_end'] <= SCRATCH + 0x10000, 'Scratch state exceeds its page')
    patched = bytearray(raw_demo)
    hookoff = fileoff(patched, HOOK)
    hooks = {}
    for name, (address, replacement) in HOOKS.items():
        check(syms[name] == address, f'{name}: callback address mismatch')
        off = fileoff(patched, address)
        prolog = struct.unpack_from('<III', patched, off)
        check(prolog[0] >> 16 == 0x3c1c and prolog[1] >> 16 == 0x279c and
              prolog[2] == 0x0399e021, f'{name}: unexpected PIC prologue')
        low = prolog[1] & 65535
        gp = ((prolog[0] & 65535) << 16) + (low if low < 32768 else low - 65536) + address
        check(gp == 0xa26cc0, f'{name}: unexpected GOT base')
        patched[off:off+8] = struct.pack('<II', 0x08000000 | (ps[replacement] >> 2), 0)
        hooks[name] = dict(address=hex(address), replacement=replacement, original=raw_demo[off:off+12].hex())
    # Single shared version literal: About display and updater equality check.
    check(patched.count(b'V1.32\0') == 1, 'Version literal is not unique')
    check(len(VERSION) + 1 == len(b'V1.32\0'),
          'VERSION must stay 5 characters; a longer literal shifts every later file offset')
    patched = patched.replace(b'V1.32\0', VERSION.encode()+b'\0')
    nulls = [(o,p) for o,p in segments(patched) if p[0] == 0]
    check(len(nulls) == 1 and nulls[0][0] == segments(patched)[-1][0], 'No final PT_NULL slot')
    check(all(p[2]+p[5] < BASE for _,p in segments(patched) if p[0] == 1), 'Patch mapping overlaps')
    appendoff = (len(patched)+65535)&~65535
    patched.extend(bytes(appendoff-len(patched)))
    patched.extend(payload)
    struct.pack_into('<8I',patched,nulls[0][0],1,appendoff,BASE,BASE,len(payload),
                     ps['__scratch_end']-BASE,7,65536)
    (out/'demo').write_bytes(patched)
    (out/'patch.dis').write_text(run('llvm-objdump','-d',out/'patch.elf'))
    # Pseudo-file round trip preserves every original inode's metadata and hardlinks.
    pseudo = out/'root.pseudo'
    run('unsquashfs','-pf',pseudo,sq)
    p = pseudo.read_bytes()
    old = re.search(rb'^release/bin/demo R (\d+) (\d+) (\d+) (\d+) .+$',p,re.M)
    check(old is not None, 'Missing demo pseudo inode')
    # mksquashfs takes "/" from the source dir, not the pseudo file; carry stock values over.
    root = re.search(rb'^/ D (\d+) (\d+) (\d+) (\d+)$',p,re.M)
    check(root is not None, 'Missing root pseudo inode')
    t,mode,uid,gid = (x.decode() for x in root.groups())
    rootargs = ['-root-time',t,'-root-mode',mode,'-root-uid',uid,'-root-gid',gid]
    # Paths are passed through a shell by mksquashfs F entries; quote them explicitly.
    import shlex
    replacement = b'release/bin/demo F '+b' '.join(old.groups())+b' cat '+shlex.quote(str(out/'demo')).encode()
    p = p[:old.start()]+replacement+p[old.end():]
    logo_data = logo.read_bytes()
    check(jpeg_size(logo_data) == (320, 375), 'Logo must be 320x375 like the stock splash')
    # Package exactly the validated bytes, even if the input is edited during compression.
    logo = out/'logo.jpg'
    logo.write_bytes(logo_data)
    line = re.search(rb'^release/assets/default/raw/images/xx/logo\.jpg R (\d+) (\d+) (\d+) (\d+) .+$', p, re.M)
    check(line is not None, 'Missing stock logo inode')
    replacement = b'release/assets/default/raw/images/xx/logo.jpg F '+b' '.join(line.groups())+b' cat '+shlex.quote(str(logo)).encode()
    p = p[:line.start()]+replacement+p[line.end():]
    pseudo.write_bytes(p)
    (out/'empty').mkdir()
    newsq = out/'rootfs.squashfs'
    epoch = struct.unpack_from('<I',sq.read_bytes(),8)[0]
    run('mksquashfs',out/'empty',newsq,'-pf',pseudo,'-noappend','-comp','lzo',
        '-b','131072','-Xcompression-level','9','-mkfs-time',epoch,*rootargs,'-processors','1','-no-progress')
    # All inodes, including demo and the logo, keep name/type/mtime/mode/uid/gid (sizes/offsets shift).
    def inodes(image):
        text = subprocess.check_output(['unsquashfs','-pf','-',str(image)]).split(b'\n# START OF DATA')[0]
        return sorted(l.split()[:6] for l in text.splitlines() if l and not l.startswith(b'#'))
    check(inodes(newsq) == inodes(sq), 'Repacked rootfs metadata differs from stock')
    blobs['recovery-update/rootfs.squashfs'] = newsq.read_bytes()
    # Stock image proves this size fits; do not enlarge beyond its padded size.
    check(len(blobs['recovery-update/rootfs.squashfs']) <= sq.stat().st_size, 'Repacked rootfs exceeds stock size')
    blobs['firmware_v20.info'] = (f'Shanling Q2\n{VERSION}\n'+''.join(
        hashlib.md5(blobs[n]).hexdigest()+'  '+n+'\n' for n in [
            'recovery-update/xImage','recovery-update/rootfs.squashfs'])).encode()
    with tarfile.open(out/'update.tar','w',format=tarfile.GNU_FORMAT) as t:
        for m in meta:
            data = blobs.get(m.name)
            if data is not None: m.size=len(data)
            t.addfile(m,io.BytesIO(data) if data is not None else None)
    manifest = dict(input_zip_sha256=ZIP_SHA, stock_demo_sha256=DEMO_SHA, source_sha256=source,
        demo_sha256=sha(patched), patch_sha256=sha(payload), update_sha256=sha((out/'update.tar').read_bytes()),
        rootfs_sha256=sha(newsq.read_bytes()), kernel_sha256=sha(blobs['recovery-update/xImage']),
        hook_address=hex(HOOK), hook_file_offset=hex(hookoff), patch_address=hex(BASE),
        patch_file_offset=hex(appendoff), patch_bytes=len(payload), ring_step_pixels=RING_STEP,
        version=VERSION, hooks=hooks, logo_sha256=sha(logo_data),
        patch_symbols={n:hex(v) for n,v in ps.items() if n.startswith('stock_')},
        tools={t:run(t,'--version').splitlines()[0] for t in ['clang','ld.lld','llvm-objcopy']})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['update_sha256','patch_bytes','version']},indent=2))

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip',type=pathlib.Path)
    ap.add_argument('--out',type=pathlib.Path,default=ROOT/'build')
    ap.add_argument('--logo',type=pathlib.Path,default=ROOT/'assets/logo.jpg',
                    help='320x375 JPEG boot splash (default: assets/logo.jpg)')
    a=ap.parse_args()
    try:
        build(a.zip,a.out.resolve(),a.logo)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        ap.error(str(exc))
