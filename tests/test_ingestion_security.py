"""Resource and preservation contracts at the offline ingestion entrypoints."""

import csv
import io
import zipfile

import pytest

from baseball_rag.db import download
from baseball_rag.db.secondary_sources import retrosheet, retrosheet_events


class Response:
    status_code = 200

    def __init__(self, chunks):
        self.chunks = chunks

    def iter_content(self, chunk_size):
        yield from self.chunks


def archive_bytes(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members:
            archive.writestr(name, value)
    return output.getvalue()


def _lahman_body(filename, *, missing=None, long_identifier=False):
    # The shipped data supplies an independent valid example, not a copied schema.
    with (download.DATA_DIR / filename).open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source)
        header, row = next(reader), next(reader)
    if missing is not None:
        index = header.index(missing)
        del header[index]
        del row[index]
    if long_identifier:
        row[header.index("playerID")] = "x" * 65_537
    output = io.StringIO()
    csv.writer(output).writerows([header, row])
    return output.getvalue().encode("utf-8")


@pytest.mark.parametrize(
    "extra",
    [
        "manifest.json",
        "pitcher_strikeout_side_events.csv",
        "batting.csv",
        "nested/",
        "../escape.csv",
    ],
)
def test_retrosheet_rejects_unexpected_members_without_changing_existing_set(tmp_path, extra):
    previous = {
        "batting.zip": b"prior archive",
        "batting.csv": b"prior CSV",
        "manifest.json": b'{"files":[]}',
        "pitcher_strikeout_side_events.csv": b"prior derived",
    }
    for name, value in previous.items():
        (tmp_path / name).write_bytes(value)
    body = archive_bytes(
        [
            ("batting.csv", "gid,value\nNYA192704180,1\n"),
            (extra, '{"files":[]}' if extra == "manifest.json" else "attacker"),
        ]
    )

    def get(url, _timeout):
        spec = next(item for item in retrosheet.ARCHIVES if url.endswith(item.archive_name))
        content = (
            body
            if spec.archive_name == "batting.zip"
            else archive_bytes([(spec.csv_name, "gid,value\nNYA192704180,1\n")])
        )
        return Response([content])

    with pytest.raises(RuntimeError):
        retrosheet.download_all(tmp_path, http_get=get)
    assert {name: (tmp_path / name).read_bytes() for name in previous} == previous


def test_lahman_failed_download_keeps_previous_complete_set(tmp_path, monkeypatch):
    previous = {name: b"previous" for name in [*download.DATA_FILES, "manifest.json"]}
    for name, value in previous.items():
        (tmp_path / name).write_bytes(value)

    def broken_chunks():
        yield b"playerID,yearID\na,2025\n"
        raise OSError("connection lost")

    monkeypatch.setattr(download.requests, "get", lambda *_, **__: Response(broken_chunks()))
    with pytest.raises(OSError, match="connection lost"):
        download.download_all(tmp_path)
    assert {name: (tmp_path / name).read_bytes() for name in previous} == previous


def test_events_reject_archive_expansion_before_parsing(tmp_path):
    body = archive_bytes([("2025NYA.EVA", "com,repeated harmless line\n" * 20_000)])
    with pytest.raises(RuntimeError, match="(ratio|budget)"):
        retrosheet_events.download_pitcher_strikeout_side_events(
            tmp_path, start_year=2025, end_year=2025, http_get=lambda *_: Response([body])
        )


@pytest.mark.parametrize("worker", ["lahman", "retrosheet", "events"])
def test_download_byte_budget_stops_stream_and_preserves_previous_files(
    tmp_path, monkeypatch, worker
):
    from dataclasses import replace

    from baseball_rag.db.ingestion_limits import DEFAULT_LIMITS

    owner = {"lahman": download, "retrosheet": retrosheet, "events": retrosheet_events}[worker]
    monkeypatch.setattr(owner, "DEFAULT_LIMITS", replace(DEFAULT_LIMITS, download_bytes=8))
    names = (
        [*download.DATA_FILES, "manifest.json"]
        if worker == "lahman"
        else ["batting.zip", "manifest.json", "pitcher_strikeout_side_events.csv"]
    )
    previous = {name: b"previous" for name in names}
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)
    consumed = []

    def chunks():
        for value in [b"12345678", b"overflow", b"never consumed"]:
            consumed.append(value)
            yield value

    def get(*_, **__):
        return Response(chunks())

    with pytest.raises(RuntimeError, match="byte budget"):
        if worker == "lahman":
            monkeypatch.setattr(download.requests, "get", get)
            download.download_all(tmp_path)
        elif worker == "retrosheet":
            retrosheet.download_all(tmp_path, http_get=get)
        else:
            retrosheet_events.download_pitcher_strikeout_side_events(
                tmp_path, start_year=2025, end_year=2025, http_get=get
            )
    assert consumed == [b"12345678", b"overflow"]
    assert {name: (tmp_path / name).read_bytes() for name in names} == previous


@pytest.mark.parametrize(
    "field,value,members",
    [
        ("members", 1, [("2025NYA.EVA", "com,a\n"), ("2025BOS.EVA", "com,b\n")]),
        ("member_bytes", 5, [("2025NYA.EVA", "com,too long\n")]),
        ("expanded_bytes", 10, [("2025NYA.EVA", "com,a\n"), ("2025BOS.EVA", "com,b\n")]),
    ],
)
def test_event_archive_budgets_apply_before_member_read(
    tmp_path, monkeypatch, field, value, members
):
    from dataclasses import replace

    from baseball_rag.db.ingestion_limits import DEFAULT_LIMITS

    monkeypatch.setattr(
        retrosheet_events, "DEFAULT_LIMITS", replace(DEFAULT_LIMITS, **{field: value})
    )
    body = archive_bytes(members)
    with pytest.raises(RuntimeError, match="budget"):
        retrosheet_events.download_pitcher_strikeout_side_events(
            tmp_path, start_year=2025, end_year=2025, http_get=lambda *_: Response([body])
        )
    assert not (tmp_path / "manifest.json").exists()


def test_lahman_install_failure_rolls_back_the_prior_set(tmp_path, monkeypatch):
    from baseball_rag.db import ingestion_limits

    previous = {name: b"previous" for name in [*download.DATA_FILES, "manifest.json"]}
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)
    monkeypatch.setattr(
        download.requests, "get", lambda url, **__: Response([_lahman_body(url.rsplit("/", 1)[-1])])
    )
    replace_file = ingestion_limits.os.replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        if not failed and destination == tmp_path / "Pitching.csv":
            failed = True
            raise OSError("install failed")
        return replace_file(source, destination)

    monkeypatch.setattr(ingestion_limits.os, "replace", fail_once)
    with pytest.raises(OSError, match="install failed"):
        download.download_all(tmp_path)
    assert {name: (tmp_path / name).read_bytes() for name in previous} == previous


def test_retrosheet_rejects_symlink_raw_csv_without_installing(tmp_path):
    output = io.BytesIO()
    member = zipfile.ZipInfo("batting.csv")
    member.create_system = 3
    member.external_attr = 0o120777 << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(member, "manifest.json")
    with pytest.raises(RuntimeError, match="symlink"):
        retrosheet.download_all(tmp_path, http_get=lambda *_: Response([output.getvalue()]))
    assert not (tmp_path / "batting.zip").exists()


def test_retrosheet_official_biodata_companions_are_not_extracted(tmp_path):
    def get(url, _timeout):
        spec = next(item for item in retrosheet.ARCHIVES if url.endswith(item.archive_name))
        members = [(spec.csv_name, "id,value\na,1\n")]
        if spec.archive_name == "biodata.zip":
            members.extend(
                (name, "unused") for name in retrosheet.BIODATA_MEMBERS if name != spec.csv_name
            )
        return Response([archive_bytes(members)])

    retrosheet.download_all(tmp_path, http_get=get)
    assert (tmp_path / "biofile0.csv").exists()
    assert not (tmp_path / "teams0.csv").exists()


def test_event_archive_with_forged_entry_count_fails_before_library_parse(tmp_path, monkeypatch):
    from dataclasses import replace

    from baseball_rag.db.ingestion_limits import DEFAULT_LIMITS

    body = bytearray(archive_bytes([("2025NYA.EVA", "com,a\n"), ("2025BOS.EVA", "com,b\n")]))
    end_record = body.rfind(b"PK\x05\x06")
    body[end_record + 8 : end_record + 12] = b"\x01\x00\x01\x00"
    monkeypatch.setattr(retrosheet_events, "DEFAULT_LIMITS", replace(DEFAULT_LIMITS, members=1))
    with pytest.raises(RuntimeError, match="member budget"):
        retrosheet_events.download_pitcher_strikeout_side_events(
            tmp_path, start_year=2025, end_year=2025, http_get=lambda *_: Response([body])
        )


@pytest.mark.parametrize("years", [range(1871, 2072), [2025, 2200]])
def test_event_year_fanout_is_checked_before_any_upstream_request(years):
    def get(*_):
        raise AssertionError("invalid year request reached upstream")

    with pytest.raises(ValueError, match="budget"):
        list(retrosheet_events.derive_pitcher_strikeout_side_events(years, http_get=get))


def test_lahman_rejects_long_physical_line_before_install(tmp_path, monkeypatch):
    previous = {name: b"previous" for name in [*download.DATA_FILES, "manifest.json"]}
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)
    # Below csv.field_size_limit: the application must impose its own line budget.
    body = _lahman_body("Batting.csv", long_identifier=True)
    monkeypatch.setattr(download.requests, "get", lambda *_, **__: Response([body]))
    with pytest.raises(RuntimeError, match="line.*budget"):
        download.download_all(tmp_path)
    assert {name: (tmp_path / name).read_bytes() for name in previous} == previous


@pytest.mark.parametrize(
    "filename,required",
    [
        ("Batting.csv", "HR"),
        ("Fielding.csv", "E"),
        ("Pitching.csv", "SO"),
        ("People.csv", "nameLast"),
    ],
)
def test_lahman_refuses_missing_published_column_without_replacing_dataset(
    tmp_path, monkeypatch, filename, required
):
    previous = {name: b"previous" for name in [*download.DATA_FILES, "manifest.json"]}
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)

    def get(url, **_kwargs):
        name = url.rsplit("/", 1)[-1]
        return Response([_lahman_body(name, missing=required if name == filename else None)])

    monkeypatch.setattr(download.requests, "get", get)
    with pytest.raises(RuntimeError, match="published.*column"):
        download.download_all(tmp_path)
    assert {name: (tmp_path / name).read_bytes() for name in previous} == previous
