import pytest

from automation_metrics import ai, cli, demo
from automation_metrics.make_client import MakeAPIError, MakeClient


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers, self.text = status, payload or {}, headers or {}, "err"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        return self.responses.pop(0)


def client(responses, page_size=2):
    sleeps = []
    c = MakeClient(
        "https://eu1.make.com/api/v2/", "tok", session=FakeSession(responses), sleep=sleeps.append, page_size=page_size
    )
    return c, sleeps


def test_pagination_reads_every_page():
    pages = [
        FakeResponse(200, {"records": [{"key": "a"}, {"key": "b"}]}),
        FakeResponse(200, {"records": [{"key": "c"}]}),
    ]
    c, _ = client(pages)
    assert [r["key"] for r in c.data_store_records(1)] == ["a", "b", "c"]
    assert c.session.calls[1][1]["pg[offset]"] == 2
    assert c.session.calls[0][0] == "https://eu1.make.com/api/v2/data-stores/1/data"
    assert c.session.headers["Authorization"] == "Token tok"


def test_retries_on_rate_limit_then_succeeds():
    c, sleeps = client(
        [FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(503), FakeResponse(200, {"records": []})]
    )
    assert c.data_store_records(1) == []
    assert sleeps == [3.0, 4.0]


def test_401_gives_a_clear_message():
    c, _ = client([FakeResponse(401)])
    with pytest.raises(MakeAPIError, match="token"):
        c.data_store_records(1)


def test_retries_exhausted():
    c, _ = client([FakeResponse(502)] * 5)
    with pytest.raises(MakeAPIError):
        c.data_store_records(1)


def test_missing_token():
    with pytest.raises(MakeAPIError, match="MAKE_API_TOKEN"):
        MakeClient("https://x", "")


CATS = [{"id": "connection_expired", "label": "Connection expired"}]


def test_ai_off_makes_no_call():
    assert ai.suggest("anything", CATS, "off") is None


def test_ai_parse_accepts_only_known_categories():
    assert (
        ai._parse('noise {"category": "connection_expired", "reason": "r"} noise', CATS)["category"]
        == "connection_expired"
    )
    assert ai._parse('{"category": "made_up"}', CATS) is None
    assert ai._parse("not json", CATS) is None


def test_ai_unknown_provider():
    with pytest.raises(ValueError):
        ai.suggest("x", CATS, "gpt")


def test_demo_data_is_deterministic_and_fictional():
    a, b = demo.sample_records(), demo.sample_records()
    assert a == b
    text = str(a).lower()
    assert "carol" not in text and "0712" not in text


def test_cli_demo_and_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "DEMO_DB", tmp_path / "demo.db")
    cli.main(["demo"])
    cli.main(["summary", "--demo", "--end", "2026-11-23", "--days", "28"])
    out = capsys.readouterr().out
    assert "Success rate" in out and "WhatsApp Status pack" in out


def test_dashboard_renders_with_demo_data():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("../dashboard/app.py", default_timeout=60)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Automation metrics"
    assert len(at.metric) == 5
