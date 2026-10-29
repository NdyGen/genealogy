import urllib.parse

import pytest

from lineage import scan

SERVER = "https://preserve2.archieven.nl/cgi-bin/iipsrv.fcgi"
FIF = "cache%2Ffonc-xyz%2F00112233445566778899aabbccddeeff.jp2"


def test_memorix_thumbnail_and_download_urls():
    assert scan.memorix(
        "https://images.memorix.nl/bhic/thumb/640x480/1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d.jpg"
    ) == ("bhic", "1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d")
    assert scan.memorix(
        "https://download-images.memorix.nl/tlb/download/fullsize/2b3c4d5e-6f70-4b2c-9d3e-4f5a6b7c8d9e.jpg"
    ) == ("tlb", "2b3c4d5e-6f70-4b2c-9d3e-4f5a6b7c8d9e")
    assert scan.memorix("https://www.archieven.nl/mi/103/?miview=ldt") is None


def test_zoomify_path_from_a_tile_request():
    tile = f"{SERVER}?Zoomify={FIF}/TileGroup0/3-2-1.jpg"
    assert scan.zoomify(tile) == (SERVER, FIF)
    assert scan.zoomify("https://preserve2.archieven.nl/embed/zoom/skin25/large/helpUp.png") is None


def test_image_name_from_archieven_preview():
    preview = (
        "http://files.archieven.nl/php/get_thumb.php?adt_id=103&toegang=1005-3797&file="
        + urllib.parse.quote(
            "3797\\Bevolkingsadministratie-Veldhoek_3797_1850-1860_Deel05_1404.jpg"
        )
    )
    assert scan.file_name(preview) == "Bevolkingsadministratie-Veldhoek_3797_1850-1860_Deel05_1404"


def test_zoomify_levels_end_at_full_size():
    levels = scan.levels(6262, 4596, 256)
    assert levels[-1] == (6262, 4596)
    assert max(levels[0]) <= 256


def test_tiles_cover_the_image_and_count_groups_over_smaller_levels():
    grid = scan.tiles(SERVER, FIF, 6262, 4596, 256)
    assert len(grid) == 25 * 18
    x, y, url = grid[-1]
    assert (x, y) == (24, 17)
    before = sum(-(-w // 256) * -(-h // 256) for w, h in scan.levels(6262, 4596, 256)[:-1])
    assert url.endswith(f"/TileGroup{(before + 17 * 25 + 24) // 256}/5-24-17.jpg")


def test_record_reference_versus_url():
    assert scan.REF.match("rmd:0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D")
    assert not scan.REF.match("https://www.openarchieven.nl/rmd:0A1B2C3D")


def test_resolver_urls_get_distinct_names():
    a = scan.url_name("https://resolver.kb.nl/resolve?urn=ddd:000000001:mpeg21:a0061")
    b = scan.url_name("https://resolver.kb.nl/resolve?urn=ddd:000000002:mpeg21:a0052")
    assert a != b and "/" not in a


def _jpeg(width, height):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "JPEG")
    return out.getvalue()


def test_only_an_image_the_size_of_a_scan_counts():
    icon, preview, scan_ = _jpeg(1268, 1268), _jpeg(400, 600), _jpeg(3000, 2200)
    assert scan._largest_scan([icon, preview]) is None
    assert scan._largest_scan([icon, scan_, preview]) == scan_


def test_mais_strip_thumbnail_becomes_full_download_with_its_signed_parameters():
    thumb = (
        "https://img.hetutrechtsarchief.nl/mi-39/hua/archiefbank/A000001/NL-UtHUA_A000001_000140.jpg"
        "?format=thumb&miadt=39&miahd=1234567890&mivast=39&rdt=20240415&open=ABC12"
    )
    assert scan.mais_download(thumb) == thumb.replace("format=thumb", "format=download")
    assert scan.mais_download(thumb.split("?")[0] + "?format=thumb") is None
    assert scan.mais_download("https://example.org/a.jpg") is None


def test_image_kinds_are_told_by_their_first_bytes():
    assert scan.image_kind(_jpeg(10, 10)) == "jpeg"
    assert scan.image_kind(b"\x89PNG\r\n\x1a\nxx") == "png"
    assert scan.image_kind(b"II*\x00xx") == scan.image_kind(b"MM\x00*xx") == "tiff"
    assert scan.image_kind(b"%PDF-1.7") == "pdf"
    assert scan.image_kind(b"<!DOCTYPE html>") is None


def test_an_html_page_is_no_scan(tmp_path):
    page = b"<!DOCTYPE html><title>Website temporarily offline</title>"
    with pytest.raises(scan.ScanError, match="not an image"):
        scan.require_image(page, "https://example.org/x")
    with pytest.raises(scan.ScanError, match="not an image"):
        scan.require_image(b"%PDF-1.7", "https://example.org/x")
    with pytest.raises(scan.ScanError, match="not an image"):
        scan._write(
            tmp_path, "x", page, scan.Provenance(ref="r", source_url="u", method="m", fetched="d")
        )
    assert not list(tmp_path.iterdir())


def test_a_memorix_outage_page_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(scan.web, "fetch", lambda *a, **k: b"<html>offline</html>")
    url = "https://download-images.memorix.nl/bhic/download/fullsize/1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d.jpg"
    with pytest.raises(scan.ScanError, match="site offline"):
        scan.fetch(url, tmp_path)
    assert not list(tmp_path.iterdir())


def test_a_tiff_is_saved_with_its_own_extension(tmp_path):
    provenance = scan.Provenance(ref="r", source_url="u", method="m", fetched="d")
    assert scan._write(tmp_path, "x", b"II*\x00data", provenance).suffix == ".tif"
