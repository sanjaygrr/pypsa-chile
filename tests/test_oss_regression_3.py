from io import BytesIO

import requests

from pypsa_chile.fetch import download, load_manifest


def test_raw_cache_distinguishes_urls_with_the_same_filename(tmp_path, monkeypatch):
    first_url = "https://first.example/data/generation.xlsx"
    second_url = "https://second.example/archive/generation.xlsx"
    payloads = {first_url: b"PK-first", second_url: b"PK-second"}
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        response = requests.Response()
        response.status_code = 200
        response.raw = BytesIO(payloads[url])
        return response

    monkeypatch.setattr(requests, "get", fake_get)

    assert download(first_url, tmp_path).read_bytes() == payloads[first_url]
    assert download(second_url, tmp_path).read_bytes() == payloads[second_url]
    cached = download(second_url, tmp_path)
    assert cached.read_bytes() == payloads[second_url]
    assert load_manifest(tmp_path)[cached.name]["url"] == second_url
    assert requested == [first_url, second_url]
