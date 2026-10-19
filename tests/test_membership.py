import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from sp500_pit import DateOutOfRange, Membership, RemoteMembership
from sp500_pit.server import make_server, resolve_port

CSV = (
    "date,tickers\n"
    '2020-01-02,"AAA,BBB,BRK.B"\n'
    '2020-01-03,"AAA,BBB,BRK.B"\n'  # duplicate set collapses
    '2020-06-01,"AAA,BRK.B,CCC"\n'
    '2021-01-04,"BRK.B,CCC,AAA"\n'
    '2021-03-01,"BBB,BRK.B,CCC"\n'
)


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text(CSV)
    return path


@pytest.fixture
def m(csv_path):
    return Membership.from_csv(csv_path)


def test_members_asof_uses_last_snapshot_on_or_before(m):
    assert m.members_asof("2020-05-31") == ["AAA", "BBB", "BRK.B"]
    assert m.members_asof("2020-06-01") == ["AAA", "BRK.B", "CCC"]
    assert m.members_asof(date(2030, 1, 1)) == ["BBB", "BRK.B", "CCC"]


def test_before_first_snapshot_raises(m):
    with pytest.raises(DateOutOfRange):
        m.members_asof("2019-12-31")


def test_vendor_spelling(m):
    assert "BRK-B" in m.members_asof("2020-02-01", "yahoo")
    assert "BRK-B.US" in m.members_asof("2020-02-01", "eodhd")
    with pytest.raises(ValueError):
        m.members_asof("2020-02-01", "bogus")


def test_union_includes_snapshot_in_force_at_start(m):
    assert m.union("2020-07-01", "2020-12-31") == ["AAA", "BRK.B", "CCC"]
    assert m.union("2020-07-01", "2021-03-01") == ["AAA", "BBB", "BRK.B", "CCC"]


def test_changes_and_intervals(m):
    assert [c["date"] for c in m.changes()] == [date(2020, 6, 1), date(2021, 3, 1)]
    assert m.changes()[0]["added"] == ["CCC"] and m.changes()[0]["removed"] == ["BBB"]
    assert m.intervals("BBB") == [(date(2020, 1, 2), date(2020, 6, 1)), (date(2021, 3, 1), None)]
    assert m.intervals("BRK-B") == [(date(2020, 1, 2), None)]


def test_coverage_reports_missing_symbols(m):
    report = m.coverage({"AAA", "BRK.B"}, dates=["2020-02-01"])
    assert report[0]["missing"] == ["BBB"] and report[0]["n_available"] == 2


def test_check_range_warns_on_stale_tail(m):
    assert m.check_range("2020-02-01", "2021-03-02") == []
    assert any("after last snapshot" in w for w in m.check_range("2020-02-01", "2022-01-01"))


def test_bad_columns_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        Membership.from_csv(bad)


def test_frame_matches_rebalancer_shape(m):
    frame = m.frame("yahoo")
    assert list(frame.columns) == ["date", "tickers"] and "BRK-B" in frame.tickers.iloc[0]


def test_service_matches_local_results(csv_path, m):
    server = make_server("127.0.0.1", 0, csv_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RemoteMembership(f"http://127.0.0.1:{server.server_port}")
        assert client.members_asof("2020-06-01", "yahoo") == m.members_asof("2020-06-01", "yahoo")
        assert client.union("2020-01-02", "2021-12-31") == m.union("2020-01-02", "2021-12-31")
        assert client.intervals("BBB") == m.intervals("BBB")
        assert client.changes() == m.changes()
        with pytest.raises(DateOutOfRange):
            client.members_asof("2019-01-01")
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/nope")
        assert err.value.code == 404
        assert json.load(urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health"))["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()


def test_content_hash_ignores_csv_formatting(tmp_path, m):
    other = tmp_path / "reordered.csv"
    other.write_text(CSV.replace('"AAA,BBB,BRK.B"', '"BRK.B,AAA,BBB"'))
    again = Membership.from_csv(other)
    assert again.sha256 != m.sha256 and again.content_hash == m.content_hash


def test_connect_pin_fails_closed(csv_path, m):
    import sp500_pit

    assert sp500_pit.connect(path=csv_path, expected_sha256=m.sha256).meta()["sha256"] == m.sha256
    with pytest.raises(sp500_pit.DatasetMismatch):
        sp500_pit.connect(path=csv_path, expected_sha256="0" * 64)


def test_restatements_report_rewritten_history(tmp_path, m):
    newer = tmp_path / "newer.csv"
    newer.write_text(CSV.replace('2020-06-01,"AAA,BRK.B,CCC"', '2020-06-01,"AAA,BRK.B,DDD"'))
    rows = m.restatements(Membership.from_csv(newer))
    assert rows[0] == dict(date=date(2020, 6, 1), added=["DDD"], removed=["CCC"])
    assert m.restatements(m) == []


def test_audit_flags_survivorship_and_stale_tail(m):
    report = m.audit(today=date(2030, 1, 1))
    by_name = {c["check"]: c["status"] for c in report["checks"]}
    assert by_name["member_count"] == "ERROR" and by_name["stale_tail"] == "WARN"
    assert by_name["ticker_reentry"] == "WARN" and by_name["closed_intervals"] == "OK"
    assert report["status"] == "ERROR" and len(report["audit_hash"]) == 64


def test_port_comes_from_env_then_dotenv_then_folder_digits_then_default(tmp_path):
    numbered = tmp_path / "8512_sp500_pit"
    plain = tmp_path / "sp500_pit"
    numbered.mkdir()
    plain.mkdir()
    assert resolve_port(numbered, {}) == 8512
    assert resolve_port(plain, {}) == 8765
    (numbered / ".env").write_text("PORT=9000\n")
    assert resolve_port(numbered, {}) == 9000
    assert resolve_port(numbered, {"PORT": "9100"}) == 9100
    with pytest.raises(ValueError):
        resolve_port(plain, {"PORT": "80"})
