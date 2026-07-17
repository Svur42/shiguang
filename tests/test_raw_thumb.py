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
