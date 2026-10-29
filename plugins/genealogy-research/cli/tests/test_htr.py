import io
import json

import pytest

from lineage import cli, htr


@pytest.fixture
def credit():
    return [150.0]


@pytest.fixture
def environment(tmp_path, monkeypatch, credit):
    cfg = tmp_path / "transkribus.env"
    cfg.write_text("LINEAGE_TRANSKRIBUS_USER=user\nLINEAGE_TRANSKRIBUS_PASSWORD=secret\n")
    monkeypatch.setenv("LINEAGE_TRANSKRIBUS_CONFIG", str(cfg))
    monkeypatch.setenv("LINEAGE_HTR_LOG", str(tmp_path / "htr.log"))
    requests = []
    content = {
        "regions": [
            {"lines": [{"text": "Willem Pieter Jan"}, {"text": "heeft gelooft"}]},
            {"lines": [{"text": "Actum XXIIII februarij 1625"}]},
        ]
    }

    def urlopen(request, timeout=0):
        url = request.full_url
        requests.append((url, request.data))
        if url == htr.TOKEN_URL:
            body = {"access_token": "tok"}
        elif url == htr.CREDITS_URL:
            return io.BytesIO(credits_xml(credit[0]))
        elif url.endswith("/v2/processes"):
            body = {"processId": 7, "status": "CREATED"}
        elif "/longpoll/7" in url:
            body = {"processId": 7, "status": "FINISHED", "content": content}
        elif url.endswith("/7/page"):
            return io.BytesIO(b"<PcGts/>")
        else:
            raise AssertionError(url)
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(htr.urllib.request, "urlopen", urlopen)
    scan = tmp_path / "929-114" / "0010.jpg"
    scan.parent.mkdir()
    scan.write_bytes(b"\xff\xd8jpeg")
    return scan, requests


def credits_xml(balance: float) -> bytes:
    package = (
        "<trpCreditPackage><active>{active}</active><expirationDate>2026-11-17T13:47:07+01:00"
        "</expirationDate><balance>{balance}</balance><product><creditType>recognition</creditType>"
        "<label>{label}</label></product></trpCreditPackage>"
    )
    return (
        "<trpCreditPackageList>"
        + package.format(active="true", balance=balance, label="Monthly Plan")
        + package.format(active="false", balance=99.0, label="Expired")
        + "</trpCreditPackageList>"
    ).encode()


def process_request(requests):
    return json.loads(next(d for u, d in requests if u.endswith("/v2/processes")))


def test_recognizes_and_saves_next_to_the_scan(environment):
    scan, requests = environment
    assert cli.main(["htr", str(scan)]) == 0
    txt = scan.parent / "htr" / "0010.txt"
    assert txt.read_text() == "Willem Pieter Jan\nheeft gelooft\n\nActum XXIIII februarij 1625"
    assert (scan.parent / "htr" / "0010.xml").read_bytes() == b"<PcGts/>"
    request = process_request(requests)
    assert request["config"]["textRecognition"]["htrId"] == htr.DUTCHESS_I
    assert request["image"]["base64"]


def test_a_recognized_scan_is_not_sent_again(environment):
    scan, requests = environment
    cli.main(["htr", str(scan)])
    requests.clear()
    assert cli.main(["htr", str(scan)]) == 0
    assert requests == []


def test_refuses_above_max(environment, tmp_path):
    scan, requests = environment
    second = scan.with_name("0011.jpg")
    second.write_bytes(scan.read_bytes())
    assert cli.main(["htr", str(scan), str(second), "--max", "1"]) == 2
    assert requests == []


def test_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("LINEAGE_TRANSKRIBUS_CONFIG", str(tmp_path / "missing.env"))
    monkeypatch.delenv("LINEAGE_TRANSKRIBUS_USER", raising=False)
    with pytest.raises(htr.HtrError):
        htr.config()


def test_config_accepts_the_old_ndygen_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "transkribus.env"
    cfg.write_text(
        "NDYGEN_TRANSKRIBUS_GEBRUIKER=user\nNDYGEN_TRANSKRIBUS_WACHTWOORD=secret\n"
        "NDYGEN_TRANSKRIBUS_URL=https://example.test\n"
    )
    monkeypatch.delenv("LINEAGE_TRANSKRIBUS_CONFIG", raising=False)
    monkeypatch.setenv("NDYGEN_TRANSKRIBUS_CONFIG", str(cfg))
    values = htr.config()
    assert values["LINEAGE_TRANSKRIBUS_USER"] == "user"
    assert values["LINEAGE_TRANSKRIBUS_PASSWORD"] == "secret"
    assert values["LINEAGE_TRANSKRIBUS_URL"] == "https://example.test"


def test_new_keys_win_over_old_ones(tmp_path, monkeypatch):
    cfg = tmp_path / "transkribus.env"
    cfg.write_text(
        "NDYGEN_TRANSKRIBUS_GEBRUIKER=old\nLINEAGE_TRANSKRIBUS_USER=new\n"
        "LINEAGE_TRANSKRIBUS_PASSWORD=secret\n"
    )
    monkeypatch.setenv("LINEAGE_TRANSKRIBUS_CONFIG", str(cfg))
    assert htr.config()["LINEAGE_TRANSKRIBUS_USER"] == "new"


def test_longpoll_timeout_keeps_waiting_and_an_empty_job_fails(environment, monkeypatch):
    scan, _ = environment
    original = htr.urllib.request.urlopen
    attempts = []

    def urlopen(request, timeout=0):
        url = request.full_url
        if "/longpoll/7" in url:
            attempts.append(url)
            if len(attempts) == 1:
                raise htr.urllib.error.HTTPError(url, 408, "timeout", {}, io.BytesIO(b"{}"))
            return io.BytesIO(json.dumps({"processId": 7, "status": "FINISHED"}).encode())
        if url.endswith("/7/result"):
            raise htr.urllib.error.HTTPError(url, 404, "no", {}, io.BytesIO(b""))
        return original(request, timeout)

    monkeypatch.setattr(htr.urllib.request, "urlopen", urlopen)
    assert cli.main(["htr", str(scan)]) == 1
    assert len(attempts) == 2
    assert not (scan.parent / "htr" / "0010.txt").exists()


def test_short_model_names_and_numbers():
    assert htr.model_id("dutchess") == htr.DUTCHESS_I
    assert htr.model_id("Zeeuws") == 210033
    assert htr.model_id("12345") == 12345
    with pytest.raises(htr.HtrError, match="unknown model"):
        htr.model_id("nonsense")


def test_another_model_gets_its_own_files_next_to_the_default_model(environment):
    scan, requests = environment
    assert cli.main(["htr", str(scan)]) == 0
    requests.clear()
    assert cli.main(["htr", str(scan), "--model", "notarieel"]) == 0
    assert process_request(requests)["config"]["textRecognition"]["htrId"] == 40382
    directory = scan.parent / "htr"
    assert (directory / "0010.txt").exists() and (directory / "0010.notarieel.txt").exists()
    assert (directory / "0010.notarieel.xml").exists()
    requests.clear()
    assert cli.main(["htr", str(scan), "--model", "notarieel"]) == 0
    assert requests == []


def test_recognitions_are_counted_per_model_and_cache_does_not_count(environment, capsys):
    scan, _ = environment
    cli.main(["htr", str(scan)])
    cli.main(["htr", str(scan)])
    cli.main(["htr", str(scan), "--model", "zeeuws"])
    capsys.readouterr()
    assert cli.main(["htr", "--count"]) == 0
    out = capsys.readouterr().out
    assert "2 recognitions" in out
    assert "dutchess (50786): 1" in out and "zeeuws (210033): 1" in out
    assert "balance: 150 credits" in out and "Monthly Plan: 150 (expires 2026-11-17)" in out
    assert "Expired" not in out
    assert cli.main(["htr", "--count", "--since", "2999-01-01"]) == 0
    assert "0 recognitions since 2999-01-01" in capsys.readouterr().out


def test_an_expired_token_is_renewed(environment, monkeypatch):
    scan, requests = environment
    second = scan.with_name("0011.jpg")
    second.write_bytes(scan.read_bytes())
    original = htr.urllib.request.urlopen
    attempts = []

    def urlopen(request, timeout=0):
        url = request.full_url
        if "/longpoll/7" in url:
            attempts.append(url)
            if len(attempts) == 1:
                raise htr.urllib.error.HTTPError(url, 401, "expired", {}, io.BytesIO(b""))
        return original(request, timeout)

    monkeypatch.setattr(htr.urllib.request, "urlopen", urlopen)
    assert cli.main(["htr", str(scan), str(second)]) == 0
    tokens = [u for u, _ in requests if u == htr.TOKEN_URL]
    assert len(tokens) == 4


def test_nothing_is_sent_without_credits(environment, credit, capsys):
    scan, requests = environment
    credit[0] = 0.0
    assert cli.main(["htr", str(scan)]) == 2
    assert "no Transkribus credits" in capsys.readouterr().err
    assert not any(u.endswith("/v2/processes") for u, _ in requests)


def test_stops_when_the_credits_run_out_halfway(environment, credit, monkeypatch, capsys):
    scan, requests = environment
    for number in ("0011", "0012"):
        scan.with_name(f"{number}.jpg").write_bytes(scan.read_bytes())
    original = htr.urllib.request.urlopen

    def urlopen(request, timeout=0):
        if "/longpoll/7" in request.full_url:
            credit[0] = 0.0
            return io.BytesIO(json.dumps({"processId": 7, "status": "FAILED"}).encode())
        return original(request, timeout)

    monkeypatch.setattr(htr.urllib.request, "urlopen", urlopen)
    images = [str(scan.with_name(f"{number}.jpg")) for number in ("0010", "0011", "0012")]
    assert cli.main(["htr", *images]) == 1
    assert sum(u.endswith("/v2/processes") for u, _ in requests) == 1
    assert "out of credits; 2 scans not submitted" in capsys.readouterr().err
