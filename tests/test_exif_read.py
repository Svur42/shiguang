import io

import pytest
from PIL import Image

import shiguang.exif_read as exif_read


def test_normalize_capture_time_converts_exif_format():
    assert exif_read._normalize_capture_time("2024:06:14 09:12:03") == "2024-06-14 09:12:03"


def test_normalize_capture_time_handles_bad_input():
    assert exif_read._normalize_capture_time("") is None
    assert exif_read._normalize_capture_time("garbage") is None
    assert exif_read._normalize_capture_time(None) is None


def test_format_day_and_time():
    day, time = exif_read._format_day_time("2024-06-14 09:12:03")
    assert day == "2024年6月14日"
    assert time == "09:12:03"


def test_format_day_time_handles_none():
    assert exif_read._format_day_time(None) == (None, None)


def test_read_metadata_returns_size_even_without_exif(tmp_path):
    p = tmp_path / "plain.png"
    Image.new("RGB", (100, 100)).save(p)

    meta = exif_read.read_metadata(p)

    assert meta["capture_time"] is None
    assert meta["cam"] is None
    assert meta["iso"] is None
    assert meta["size"] is not None
    for key in ("capture_time", "iso", "shutter", "aperture", "focal", "cam", "size"):
        assert key in meta


def test_read_metadata_reads_exif_from_jpeg_with_tags(tmp_path):
    piexif = pytest.importorskip("piexif")
    exif_dict = {
        "0th": {piexif.ImageIFD.Model: b"Canon EOS R5"},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2024:06:14 09:12:03",
            piexif.ExifIFD.ISOSpeedRatings: 100,
            piexif.ExifIFD.FNumber: (28, 10),
            piexif.ExifIFD.ExposureTime: (1, 400),
            piexif.ExifIFD.FocalLength: (85, 1),
        },
    }
    p = tmp_path / "shot.jpg"
    Image.new("RGB", (100, 100)).save(p)
    piexif.insert(piexif.dump(exif_dict), str(p))

    meta = exif_read.read_metadata(p)

    assert meta["capture_time"] == "2024-06-14 09:12:03"
    assert meta["cam"] == "Canon EOS R5"
    assert meta["iso"] == 100
    assert meta["aperture"] == "f/2.8"
    assert meta["shutter"] == "1/400s"
    assert meta["focal"] == "85mm"
