#!/usr/bin/env python3
"""Turn a picture into the y4m file Chromium's fake camera plays.

    python3 tests/png2y4m.py <image.png|jpg> <out.y4m> [--frames N] [--size WxH]
    python3 tests/png2y4m.py --grey WxH <out.y4m> [--frames N]

Chromium, launched with --use-fake-device-for-media-stream and
--use-file-for-fake-video-capture=<file>.y4m, hands the file's frames to
getUserMedia as if a camera had taken them, and reports the file's size as
videoWidth and videoHeight. So a photograph written out at its own portrait
size lets a test stand the phone exactly where the photograph was taken,
and a stencil can be scored against the very picture it was cut from.

Y4M is a one-line text header followed by raw frames, each "FRAME\\n" and
then the three I420 planes: Y at full size, then Cb and Cr at half size in
both directions. The picture is converted with BT.601's limited-range
matrix (Y' from 16 to 235, chroma centred on 128), which is what a camera
delivers and what Chromium expects of a y4m; Pillow's own YCbCr mode is the
full-range JPEG variant, so it is not used. Chromium wants even dimensions
for the half-size chroma, so an odd edge loses one pixel. One frame is
converted and repeated N times (default 30, a second at 30 fps): a fake
camera showing a still.

--grey WxH writes a uniform mid-grey frame, every byte of every plane 128,
for the test that must not pass.

Not part of the build, and needs Pillow, like pipeline/stencil.py. Other
scripts can call write_y4m(image, path, frames) with a Pillow image.
"""

import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

FRAMES = 30
GREY = 128

# BT.601 limited range, as 4-tuples for Image.convert("L", matrix), which
# computes a*R + b*G + c*B + d and rounds. The coefficients are the
# standard's, over 255 so they take 8-bit RGB.
Y_MATRIX = (65.481 / 255, 128.553 / 255, 24.966 / 255, 16.0)
CB_MATRIX = (-37.797 / 255, -74.203 / 255, 112.0 / 255, 128.0)
CR_MATRIX = (112.0 / 255, -93.786 / 255, -18.214 / 255, 128.0)


def to_i420(image):
    """The picture as I420: (width, height, Y bytes, Cb bytes, Cr bytes).

    The EXIF orientation is applied first so a portrait photograph is
    portrait; an odd width or height is cropped to even because the chroma
    planes are half size. The chroma is computed at full size and then
    averaged over 2x2 blocks, which is what the 4:2:0 in I420 means."""
    im = ImageOps.exif_transpose(image).convert("RGB")
    w, h = im.size
    w -= w % 2
    h -= h % 2
    if w < 2 or h < 2:
        raise SystemExit(f"png2y4m: the picture is {im.size[0]}x{im.size[1]}, too small for I420")
    if (w, h) != im.size:
        im = im.crop((0, 0, w, h))
    y = im.convert("L", Y_MATRIX)
    u = im.convert("L", CB_MATRIX).reduce(2)
    v = im.convert("L", CR_MATRIX).reduce(2)
    return w, h, y.tobytes(), u.tobytes(), v.tobytes()


def write_frames(path, w, h, y, u, v, frames=FRAMES):
    """Write the y4m: the header, then the same frame `frames` times."""
    if w % 2 or h % 2:
        raise SystemExit(f"png2y4m: I420 needs even dimensions, not {w}x{h}")
    if len(y) != w * h or len(u) != (w // 2) * (h // 2) or len(v) != len(u):
        raise SystemExit("png2y4m: the planes do not match the size")
    if frames < 1:
        raise SystemExit("png2y4m: --frames must be at least 1")
    header = f"YUV4MPEG2 W{w} H{h} F30:1 Ip A1:1 C420jpeg\n".encode("ascii")
    frame = b"FRAME\n" + y + u + v
    with open(path, "wb") as f:
        f.write(header)
        for _ in range(frames):
            f.write(frame)
    return w, h


def write_y4m(image, path, frames=FRAMES):
    """Convert a Pillow image and write it as a y4m of `frames` identical
    frames. Returns the (width, height) the fake camera will report."""
    w, h, y, u, v = to_i420(image)
    return write_frames(path, w, h, y, u, v, frames)


def write_grey(path, w, h, frames=FRAMES):
    """A uniform mid-grey y4m: 128 in every plane, so no edges anywhere."""
    w -= w % 2
    h -= h % 2
    y = bytes([GREY]) * (w * h)
    u = bytes([GREY]) * ((w // 2) * (h // 2))
    return write_frames(path, w, h, y, u, u, frames)


def parse_size(text, what):
    m = re.fullmatch(r"(\d+)x(\d+)", text or "")
    if not m:
        raise SystemExit(f"png2y4m: {what} wants WxH, like 600x800, not {text!r}")
    return int(m.group(1)), int(m.group(2))


def usage():
    raise SystemExit(
        "usage: png2y4m.py <image.png|jpg> <out.y4m> [--frames N] [--size WxH]\n"
        "       png2y4m.py --grey WxH <out.y4m> [--frames N]"
    )


def main(argv):
    frames, size, grey, paths = FRAMES, None, None, []
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--frames":
            if not args or not args[0].isdigit():
                raise SystemExit("png2y4m: --frames wants a whole number")
            frames = int(args.pop(0))
        elif a == "--size":
            size = parse_size(args.pop(0) if args else None, "--size")
        elif a == "--grey":
            # The size may follow --grey directly, or come from --size.
            grey = True
            if args and re.fullmatch(r"\d+x\d+", args[0]):
                size = parse_size(args.pop(0), "--grey")
        elif a.startswith("-") and a != "-":
            usage()
        else:
            paths.append(a)

    if grey:
        if len(paths) != 1:
            usage()
        if size is None:
            raise SystemExit("png2y4m: the grey frame needs a size: --grey WxH or --size WxH")
        out = Path(paths[0])
        w, h = write_grey(out, size[0], size[1], frames)
        print(f"wrote {out} grey {w}x{h}, {frames} frame{'s' if frames != 1 else ''}")
        return

    if len(paths) != 2:
        usage()
    src, out = Path(paths[0]), Path(paths[1])
    if not src.is_file():
        raise SystemExit(f"png2y4m: no picture at {src}")
    with Image.open(src) as photo:
        # The orientation is applied here as well as in to_i420 so that
        # --size sees the portrait photograph, not the landscape file.
        im = ImageOps.exif_transpose(photo)
        if size is not None:
            # The caller says what size the camera should report; the
            # picture is stretched to it, so keep the aspect ratio yourself.
            im = im.resize(size, Image.LANCZOS)
        w, h = write_y4m(im, out, frames)
    print(f"wrote {out} {w}x{h} from {src.name}, {frames} frame{'s' if frames != 1 else ''}")


if __name__ == "__main__":
    main(sys.argv[1:])
