import pytest

from lineage import rat


def _item(unitid, cpath, title, scancount):
    return {
        "unitid": [unitid],
        "cpath": cpath,
        "title": title,
        "unitdate": ["1632"],
        "scancount": scancount,
    }


@pytest.fixture
def offline(monkeypatch):
    calls = []

    def fake_get(path, params):
        calls.append((path, params))
        if path == "findingaiditems":
            items = [_item("412", "28.23", "Voogdij Hendriks", 23)]
            if "keywords" in params:
                items.append({"title": "Schepenbank van Veldhoek"})
            return {"meta": {"numFound": 2}, "findingAidItems": items}
        start = int(params.get("start", 0))
        batch = [
            {"id": f"id{n}", "name": f"0929_0412_{n:04d}"}
            for n in range(start + 1, min(start + 10, 23) + 1)
        ]
        return {"scans": {"scans": batch, "scancount": 23}}

    monkeypatch.setattr(rat, "_get", fake_get)
    return calls


def test_search_skips_the_archive_itself(offline):
    total, items = rat.search("Hendriks")
    assert total == 2
    assert [s.inventory for s in items] == ["412"]


def test_item_pages_through_all_scans(offline):
    s = rat.item("412")
    assert len(s.scans) == 23
    assert s.scans[-1].number == 23 and s.scans[-1].name == "0929_0412_0023"
    assert s.citation(s.scans[0]) == "RAT 929 inv. 412, scan 1 (0929_0412_0001): Voogdij Hendriks"
    assert [p.get("start") for path, p in offline if path.startswith("scans/")] == [0, 10, 20]


def test_unknown_scan_number_is_refused(offline, tmp_path):
    with pytest.raises(rat.RatError):
        rat.download(rat.item("412"), [24], tmp_path)


def test_parse_numbers():
    assert rat.parse_numbers("3,5,10-12") == [3, 5, 10, 11, 12]


def test_crop(tmp_path):
    from PIL import Image

    page = tmp_path / "p.jpg"
    Image.new("RGB", (200, 100), "white").save(page)
    out = rat.crop(page, (0.5, 0.0, 1.0, 0.5), tmp_path / "c.jpg", scale=2)
    with Image.open(out) as crop:
        assert crop.size == (200, 100)
    with pytest.raises(rat.RatError):
        rat.crop(page, (0.5, 0.0, 0.4, 0.5), tmp_path / "x.jpg")


def test_item_prefers_the_register_over_its_series(monkeypatch):
    def fake_get(path, params):
        if path == "findingaiditems":
            return {
                "findingAidItems": [
                    _item("89", "40", "Zaken van registratie 1525-1810 (1)", 0),
                    _item("89", "40.1", "Protocol. Register.", 328),
                ]
            }
        return {"scans": {"scans": [], "scancount": 0}}

    monkeypatch.setattr(rat, "_get", fake_get)
    assert rat.item("89").title == "Protocol. Register."


class _Answer:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.data


@pytest.fixture
def server(monkeypatch, tmp_path):
    """Fake Memorix behind the real brake; the brake state lives in tmp_path."""
    import urllib.error

    monkeypatch.setenv("LINEAGE_RAT_CACHE", str(tmp_path / "rem"))
    monkeypatch.setattr(rat, "INTERVAL", 0)
    calls = []
    status = {"code": 200}

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if status["code"] != 200:
            raise urllib.error.HTTPError(request.full_url, status["code"], "no", {}, None)
        body = (
            b'{"findingAidItems": []}'
            if "findingaiditems" in request.full_url
            else status.get("body", b"\xff\xd8jpeg")
        )
        return _Answer(body)

    monkeypatch.setattr(rat.urllib.request, "urlopen", fake_urlopen)
    return calls, status


def test_429_stops_all_traffic_without_retrying(server):
    calls, status = server
    status["code"] = 429
    with pytest.raises(rat.RatError, match="429"):
        rat._fetch("https://example/a", 5)
    assert len(calls) == 1
    status["code"] = 200
    with pytest.raises(rat.RatError, match="locked out"):
        rat._fetch("https://example/b", 5)
    assert len(calls) == 1


def test_403_stops_traffic_for_hours(server):
    calls, status = server
    status["code"] = 403
    with pytest.raises(rat.RatError):
        rat._fetch("https://example/a", 5)
    assert rat.throttle_state()["locked_until"] - rat.time.time() > 5 * 3600


def test_probe_lifts_a_standstill_once_the_server_answers(server):
    calls, status = server
    status["code"] = 429
    with pytest.raises(rat.RatError):
        rat._fetch("https://example/a", 5)
    status["code"] = 200
    assert "lifted" in rat.probe()
    assert "locked_until" not in rat.throttle_state()


def test_requests_keep_the_interval_across_calls(server, monkeypatch):
    slept = []
    monkeypatch.setattr(rat, "INTERVAL", 3)
    monkeypatch.setattr(rat.time, "sleep", slept.append)
    rat._fetch("https://example/a", 5)
    rat._fetch("https://example/b", 5)
    assert slept and 0 < slept[0] <= 3


def test_scans_and_api_answers_are_fetched_once(server, tmp_path):
    calls, _ = server
    rat._get("findingaiditems", {"x": 1})
    rat._get("findingaiditems", {"x": 1})
    found = rat.Item("929", "1", "1", "t", "", 1, [rat.Scan(1, "abc", "0929_0001_0001")])
    rat.download(found, [1], tmp_path / "een")
    rat.download(found, [1], tmp_path / "twee")
    assert (tmp_path / "twee" / "929-1" / "0001.jpg").read_bytes() == b"\xff\xd8jpeg"
    assert len(calls) == 2


def test_an_outage_page_is_not_cached_as_a_scan(server, tmp_path):
    _, status = server
    status["body"] = b"<!DOCTYPE html><title>Website temporarily offline</title>"
    found = rat.Item("929", "1", "1", "t", "", 1, [rat.Scan(1, "abc", "0929_0001_0001")])
    with pytest.raises(rat.RatError, match="not a JPEG"):
        rat.download(found, [1], tmp_path)
    assert not (tmp_path / "929-1" / "0001.jpg").exists()
    assert not list((tmp_path / "rem").rglob("abc*"))
