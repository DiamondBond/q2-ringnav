# Custom boot logo

The Q2 splash shown on the screen at power-on is a JPEG inside the rootfs. There is no on-device setting; changing it is part of building a firmware update.

| What | Where |
| --- | --- |
| Image | `/release/assets/default/raw/images/xx/logo.jpg` (320x375 JPEG) |
| Drawn by | `/usr/bin/display_logo` (libjpeg, writes `/dev/fb0`) |
| Started by | `/etc/init.d/S11logo_display_shell`, as soon as `/dev/fb0` exists |

## Build an update with a custom logo

Every build replaces the splash with `assets/logo.jpg`. Pass another 320x375 JPEG with `--logo` to use your own:

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-logo --logo my-logo.jpg
```

Flash `/tmp/q2-logo/update.tar` the normal way: copy it to the root of the microSD card, then **System settings → System Update → TF card update**. The update keeps the scroll-wheel patch, and **About** still shows the version from the build (currently `V1.9R`).

## Making a logo that works

- **Canvas: exactly 320x375 pixels.** `display_logo` does not scale the image, so fit the artwork yourself: scale it to the 320 px width, keep its aspect ratio, and centre it vertically (the example sits at y=58 on a black canvas). The build rejects any other size.
- **Format: baseline JPEG.** No PNG, no alpha.
- **Keep it small.** JPEG data barely compresses and the repacked rootfs must stay within the stock image size (50,442,240 bytes). The stock splash is 47.8 KB and a rebuilt rootfs leaves only about 4 KB of slack, so keep the file around 50 KB or less; re-save at lower quality if the build fails with `Repacked rootfs exceeds stock size`. `assets/logo.jpg` is 16.6 KB.

To check what landed in the image:

```sh
unsquashfs -cat /tmp/q2-logo/rootfs.squashfs release/assets/default/raw/images/xx/logo.jpg | sha256sum
sha256sum my-logo.jpg
```

## Notes

- Only `rootfs.squashfs` and the kernel are shipped in `update.tar`; the bootloader is untouched. Anything displayed before Linux starts is not affected.
- `manifest.json` records the logo's SHA-256, and identical inputs (including the logo) still produce an identical `update.tar`.
- The splash is only shown while the app starts, so a logo you dislike is cosmetic: flash a corrected update to replace it.
