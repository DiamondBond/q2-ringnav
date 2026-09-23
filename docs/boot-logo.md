# Custom boot logo

The Q2 splash shown on the screen at power-on is a JPEG inside the rootfs. There is no on-device setting; changing it is part of building a firmware update.

| What       | Where                                                             |
| ---------- | ----------------------------------------------------------------- |
| Image      | `/release/assets/default/raw/images/xx/logo.jpg` (320x375 JPEG)   |
| Drawn by   | `/usr/bin/display_logo` (libjpeg, writes `/dev/fb0`)              |
| Started by | `/etc/init.d/S11logo_display_shell`, as soon as `/dev/fb0` exists |

## Build an update with a custom logo

Every build replaces the splash with `assets/logo.jpg`. Pass another 320x375 JPEG with `--logo` to use your own:

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-logo --logo my-logo.jpg
```

Flash `/tmp/q2-logo/update.tar` the normal way: copy it to the root of the microSD card, then **System settings → System Update → TF card update**. The update keeps the scroll-wheel patch, and **About** still shows the version from the build (currently `V1.9R`).

## Making a logo that works

- **Orientation: rotate upright artwork 90° clockwise before fitting it.** The stock JPEG is stored sideways because of the framebuffer orientation. The supplied SHANLING logo therefore reads downward along the left side of the stored JPEG and appears upright on the device.
- **Canvas: exactly 320x375 pixels, black.** `display_logo` does not scale the image. Fit the rotated artwork within both dimensions, preserve its aspect ratio, and centre it horizontally and vertically without cropping. The build rejects any other size.
- **Format: baseline JPEG.** No PNG, no alpha.
- **Keep it small.** JPEG data barely compresses and the repacked rootfs must stay within the stock image size (50,442,240 bytes). The stock splash is 47.8 KB and a rebuilt rootfs leaves only about 4 KB of slack, so keep the file around 50 KB or less; re-save at lower quality if the build fails with `Repacked rootfs exceeds stock size`. `assets/logo.jpg` is about 16.5 KB.

The supplied logo comes from the [original artwork](https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRA0yLsPKygK-EqPHDCqGfsbNtwv2mp9Lk4l-aqDei6Qy85qhC-mONCnwo&s=10), transformed directly with ImageMagick. The downloaded source is a 428x346 PNG despite the URL having no filename. To reproduce the transform from that source:

```sh
magick original-logo.png -background black -alpha remove -alpha off -rotate 90 \
  -resize 320x375 -gravity center -extent 320x375 -colorspace sRGB -type TrueColor \
  -strip -interlace none -quality 92 assets/logo.jpg
```

To check what landed in the image:

```sh
unsquashfs -cat /tmp/q2-logo/rootfs.squashfs release/assets/default/raw/images/xx/logo.jpg | sha256sum
sha256sum my-logo.jpg
```

## Notes

- Only `rootfs.squashfs` and the kernel are shipped in `update.tar`; the bootloader is untouched. Anything displayed before Linux starts is not affected.
- `manifest.json` records the logo's SHA-256, and identical inputs (including the logo) still produce an identical `update.tar`.
- The splash is only shown while the app starts, so a logo you dislike is cosmetic: flash a corrected update to replace it.
