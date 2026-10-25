import io
import pytest
from PIL import Image

import shiguang.raw_thumb as raw_thumb


def test_extract_thumbnail_from_jpeg(tmp_path):
    img = Image.new("RGB", (800, 600), color=(120, 200, 80))
    src = tmp_path / "sample.jpg"
    img.save(src, format="JPEG")

    thumb_bytes = raw_thumb.extract_thumbnail(src, max_size=256)

    thumb_img = Image.open(io.BytesIO(thumb_bytes))
    assert thumb_img.format == "JPEG"
    assert max(thumb_img.size) <= 256


def test_extract_thumbnail_never_converts_at_full_resolution(tmp_path, monkeypatch):
    """提速关键：大图(相机内嵌全尺寸JPEG)要先按 DCT 缩放解码再转色，不能先 convert 把
    6000px 级全分辨率整张解出来——那正是快速滑动时缩略图迟迟出不来的元凶之一。"""
    src = tmp_path / "big.jpg"
    Image.new("RGB", (4000, 3000), color=(90, 140, 200)).save(src, format="JPEG")
    seen = []
    real_convert = Image.Image.convert

    def spy(self, *a, **k):
        seen.append(self.size)
        return real_convert(self, *a, **k)

    monkeypatch.setattr(Image.Image, "convert", spy)

    thumb = Image.open(io.BytesIO(raw_thumb.extract_thumbnail(src, max_size=512)))

    assert max(thumb.size) == 512
    assert seen and max(max(s) for s in seen) <= 512


def test_extract_thumbnail_preview_size_and_rgba_source(tmp_path):
    """2560 预览档尺寸正确；带透明通道的 PNG 也能出 RGB JPEG。"""
    big = tmp_path / "big.jpg"
    Image.new("RGB", (3600, 2400), color=(10, 20, 30)).save(big, format="JPEG")
    png = tmp_path / "alpha.png"
    Image.new("RGBA", (900, 600), color=(10, 200, 30, 120)).save(png)

    preview = Image.open(io.BytesIO(raw_thumb.extract_thumbnail(big, max_size=2560)))
    small = Image.open(io.BytesIO(raw_thumb.extract_thumbnail(png, max_size=512)))

    assert preview.size == (2560, 1707)
    assert small.mode == "RGB" and max(small.size) == 512


def test_extract_thumbnail_rejects_unknown_extension(tmp_path):
    src = tmp_path / "sample.txt"
    src.write_text("not a photo")
    with pytest.raises(ValueError):
        raw_thumb.extract_thumbnail(src)


@pytest.mark.skipif(
    not (__import__("pathlib").Path(__file__).parent / "fixtures" / "sample.cr2").exists(),
    reason="需要在 tests/fixtures/sample.cr2 放一个真实的RAW样片才能测这条路径，见 fixtures/README.md",
)
def test_extract_thumbnail_from_real_raw_file():
    from pathlib import Path

    sample = Path(__file__).parent / "fixtures" / "sample.cr2"
    thumb_bytes = raw_thumb.extract_thumbnail(sample, max_size=256)
    thumb_img = Image.open(io.BytesIO(thumb_bytes))
    assert max(thumb_img.size) <= 256


def test_palette_images_are_converted_before_resizing(tmp_path, monkeypatch):
    """审查#7：调色板(P)/1-bit 图先缩再转色时 Pillow 只能最近邻采样，会出锯齿——这两种模式先转色。"""
    src = tmp_path / "pal.png"
    Image.linear_gradient("L").resize((1200, 800)).convert("P").save(src)
    modes = []
    real_thumbnail = Image.Image.thumbnail

    def spy(self, *a, **k):
        modes.append(self.mode)
        return real_thumbnail(self, *a, **k)

    monkeypatch.setattr(Image.Image, "thumbnail", spy)

    raw_thumb.extract_thumbnail(src, max_size=256)

    assert modes and modes[0] not in ("P", "1")


def test_extract_full_passes_plain_jpeg_through_untouched(tmp_path):
    """原图不再解码+重新压缩：普通 JPEG(无方向标记、不超上限)原样给出，画质就是原文件。"""
    src = tmp_path / "plain.jpg"
    Image.new("RGB", (900, 600), (90, 140, 200)).save(src, quality=95)
    assert raw_thumb.extract_full(str(src)) == src.read_bytes()


def test_extract_full_reencodes_when_exif_orientation_present(tmp_path):
    """带 EXIF 方向标记的 JPEG 不原样给(浏览器会自动转，和不带 EXIF 的预览/缩略图方向对不上)。"""
    src = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (900, 600), (90, 140, 200)).save(src, quality=95, exif=exif)
    out = raw_thumb.extract_full(str(src))
    assert out != src.read_bytes()
    img = Image.open(io.BytesIO(out))
    assert img.size == (900, 600) and img.getexif().get(0x0112) is None


def test_extract_full_still_caps_oversized_images(tmp_path):
    src = tmp_path / "huge.jpg"
    Image.new("RGB", (1200, 800), (10, 20, 30)).save(src)
    img = Image.open(io.BytesIO(raw_thumb.extract_full(str(src), max_size=600)))
    assert max(img.size) == 600


def test_downscale_jpeg_makes_small_tier():
    buf = io.BytesIO()
    Image.new("RGB", (512, 341), (200, 100, 50)).save(buf, format="JPEG")
    img = Image.open(io.BytesIO(raw_thumb.downscale_jpeg(buf.getvalue(), 256)))
    assert max(img.size) == 256 and img.format == "JPEG"


def test_extract_full_reencodes_when_icc_profile_present(tmp_path):
    """带 ICC 的 JPEG 不原样给：预览不带 ICC，换原图那一刻会色变。"""
    from PIL import ImageCms
    src = tmp_path / "icc.jpg"
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (300, 200), (90, 140, 200)).save(src, icc_profile=icc)
    assert raw_thumb.extract_full(str(src)) != src.read_bytes()
