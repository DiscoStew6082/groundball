# fmt: off
"""Bounded fail-closed pre-publication scanner for provider-specific residue."""
# ruff: noqa: E501, E701, E702
from __future__ import annotations

import argparse
import codecs
import fnmatch
import ipaddress
import json
import re
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import IO, Any, Iterable, Sequence
from urllib.parse import urlsplit

CHUNK_BYTES, OVERLAP_CHARACTERS, MAX_ARCHIVE_MEMBERS, MAX_ARTIFACTS = 65_536, 512, 4096, 16
MAX_POLICY_BYTES, MAX_RULES_PER_KIND = 65_536, 64
MAX_ARCHIVE_DEPTH, MAX_ARCHIVE_BYTES, MAX_ARCHIVE_MEMBER_BYTES = 2, 2_147_483_648, 805_306_368
MAX_NESTED_ARCHIVE_BYTES, MAX_COMPRESSION_RATIO = 134_217_728, 100
_ALLOWED_BINARY_SUFFIXES = {".png"}; _ARCHIVE_SUFFIXES = (".zip", ".whl", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz"); _NESTED_ARCHIVES = (".zip", ".whl", ".tar", ".tar.gz", ".tar.xz", ".tgz"); _ARCHIVE_LIKE = (*_ARCHIVE_SUFFIXES, ".7z", ".rar", ".jar", ".gz", ".bz2", ".xz"); _ALLOWED_HIDDEN = {".git", ".github"}
_ALLOWED_PUBLIC_HOSTS = frozenset("astral.sh baseballsavant.mlb.com blogs.fangraphs.com creativecommons.org en.wikipedia.org example.com files.pythonhosted.org github.com huggingface.co img.shields.io modelcontextprotocol.io opencollective.com pypi.org raw.githubusercontent.com registry.npmjs.org sabr.org stathead.com statsapi.mlb.com svelte.dev tidelift.com www.example.com www.fangraphs.com www.mlb.com www.retrosheet.org www.statmuse.com www.w3.org".split())  # noqa: E501  # fmt: skip
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PERSONAL_PATH = re.compile(r"/(?:Users|Volumes)/[^/\s\"']+")
_NAME_SEGMENTS = r"(?:[A-Za-z0-9]+[_-])*"
_NAME_SUFFIX = r"(?:[_-][A-Za-z0-9]+)*"
_SENSITIVE_ASSIGNMENT = re.compile(rf"(?i)\b(?P<name>{_NAME_SEGMENTS}(?:credential|api[_-]?key|secret|token|password|authorization|request[_-]?identity|user[_-]?agent|client[_-]?ip){_NAME_SUFFIX})\s*[:=]")  # noqa: E501
_RESOURCE_ASSIGNMENT = re.compile(rf"(?i)\b(?P<name>{_NAME_SEGMENTS}(?:account|organization|org|project|store|deployment)[_-]id{_NAME_SUFFIX})\s*[:=]")  # noqa: E501
_LEXEME = re.compile(r"[A-Za-z0-9_@./:+-]+")
_RULE_ID = re.compile(r"[a-z][a-z0-9.-]{0,63}")
@dataclass(frozen=True, order=True)
class Finding: path: str; line: int; rule_id: str; excerpt: str
def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")  # noqa: E501
def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result: raise ValueError("invalid deny policy")
        result[key] = value
    return result
def _load_policy(path: Path | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if path is None: return [], []
    if path.is_symlink() or not path.is_file(): raise ValueError("invalid deny policy")
    try:
        raw = path.read_bytes()
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid deny policy") from error
    if not raw or len(raw) > MAX_POLICY_BYTES or not isinstance(data, dict) or set(data) != {"schema_version", "exact_rules", "glob_rules"}: raise ValueError("invalid deny policy")
    try:
        canonical = _canonical_json(data)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid deny policy") from error
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or canonical != raw: raise ValueError("invalid deny policy")
    exact = _validate_rules(data["exact_rules"], "value", glob=False)
    globs = _validate_rules(data["glob_rules"], "pattern", glob=True)
    ids = [rule["rule_id"] for rule in exact + globs]
    if len(ids) != len(set(ids)): raise ValueError("invalid deny policy")
    return exact, globs
def _validate_rules(value: Any, field: str, *, glob: bool) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_RULES_PER_KIND: raise ValueError("invalid deny policy")
    rules: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"rule_id", field}: raise ValueError("invalid deny policy")
        rule_id, pattern = item["rule_id"], item[field]
        if not isinstance(rule_id, str) or not _RULE_ID.fullmatch(rule_id): raise ValueError("invalid deny policy")
        if not isinstance(pattern, str) or not pattern or len(pattern) > 256 or any(ord(char) < 32 for char in pattern):
            raise ValueError("invalid deny policy")
        if glob and (len(pattern) > 128 or pattern.count("*") + pattern.count("?") > 8): raise ValueError("invalid deny policy")
        rules.append(item)
    keys = [(item["rule_id"], item[field]) for item in rules]
    patterns = [item[field] for item in rules]
    if keys != sorted(keys) or len(keys) != len(set(keys)) or len(patterns) != len(set(patterns)): raise ValueError("invalid deny policy")
    return rules
def _git_files(root: Path) -> list[Path] | None:
    command = ["git", "-C", str(root)]
    try:
        top = subprocess.run([*command, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
            return None
        result = subprocess.run([*command, "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    paths: list[Path] = []
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        try:
            candidate = root / raw_name.decode("utf-8")
            if candidate.exists() or candidate.is_symlink():
                paths.append(candidate)
        except UnicodeDecodeError:
            paths.append(root / "<invalid-git-path>")
    return paths
def _tree_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if ".git" not in path.relative_to(root).parts and (path.is_file() or path.is_symlink())]
def _artifact_files(root: Path, artifacts: Sequence[str | Path]) -> list[Path]:
    if len(artifacts) > MAX_ARTIFACTS:
        raise ValueError("at most 16 artifacts are allowed")
    selected: list[Path] = []
    for supplied in artifacts:
        candidate = Path(supplied)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_symlink() or not candidate.exists():
            raise ValueError("invalid artifact")
        try:
            candidate.resolve().relative_to(root)
        except (OSError, ValueError) as error:
            raise ValueError("invalid artifact") from error
        if candidate.is_file():
            selected.append(candidate)
        elif candidate.is_dir():
            selected.extend(_tree_files(candidate))
        else:
            raise ValueError("invalid artifact")
    return selected
def _url_allowed(value: str) -> bool:
    parsed = urlsplit(value.rstrip(".,);]"))
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in _ALLOWED_PUBLIC_HOSTS
@lru_cache(maxsize=128)
def _glob_anchor(pattern: str) -> str: return max(re.split(r"[*?]", re.sub(r"\[[^]]*\]", "*", pattern)), key=len)
def _line_findings(relative: str, number: int, line: str, exact: list[dict[str, str]], globs: list[dict[str, str]], *, incomplete: bool = False) -> list[Finding]:
    exact_matches = [rule for rule in exact if rule["value"] in line]
    glob_candidates = [rule for rule in globs if not _glob_anchor(rule["pattern"]) or _glob_anchor(rule["pattern"]) in line]
    if not exact_matches and not glob_candidates and not any(marker in line for marker in ("/", "=", ":")): return []
    found: list[Finding] = []
    if _PERSONAL_PATH.search(line):
        found.append(Finding(relative, number, "personal-absolute-path", "<redacted>"))
    for match in _URL.finditer(line):
        if incomplete and match.end() == len(line):
            continue
        if not _url_allowed(match.group()):
            found.append(Finding(relative, number, "nonpublic-url", "<redacted>"))
    resource_match = _RESOURCE_ASSIGNMENT.search(line)
    assignment_match = _SENSITIVE_ASSIGNMENT.search(line)
    if resource_match:
        found.append(Finding(relative, number, "resource-identifier-assignment", f"{resource_match.group('name')}=<redacted>"[-120:]))
    elif assignment_match:
        found.append(Finding(relative, number, "sensitive-assignment", f"{assignment_match.group('name')}=<redacted>"[-120:]))
    for rule in exact_matches: found.append(Finding(relative, number, rule["rule_id"], "<redacted>"))
    lexemes = _LEXEME.findall(line) if glob_candidates else []
    for rule in glob_candidates:
        if fnmatch.fnmatchcase(line, rule["pattern"]) or any(fnmatch.fnmatchcase(item, rule["pattern"]) for item in lexemes):
            found.append(Finding(relative, number, rule["rule_id"], "<redacted>"))
    return found
def _scan_stream(stream: IO[bytes], relative: str, exact: list[dict[str, str]], globs: list[dict[str, str]]) -> list[Finding]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    overlap = ""
    newlines = 0
    findings: list[Finding] = []
    try:
        while raw := stream.read(CHUNK_BYTES):
            if b"\0" in raw:
                raise UnicodeError
            chunk = decoder.decode(raw)
            window = overlap + chunk
            base_line = 1 + newlines - overlap.count("\n")
            scannable = window[:-OVERLAP_CHARACTERS]
            lines = scannable.splitlines() or [scannable]
            for index, line in enumerate(lines):
                incomplete = index == len(lines) - 1 and not scannable.endswith(("\n", "\r"))
                findings.extend(_line_findings(relative, base_line + index, line, exact, globs, incomplete=incomplete))
            newlines += chunk.count("\n")
            overlap = window[-OVERLAP_CHARACTERS:]
        decoder.decode(b"", final=True)
        base_line = 1 + newlines - overlap.count("\n")
        for index, line in enumerate(overlap.splitlines() or [overlap]):
            findings.extend(_line_findings(relative, base_line + index, line, exact, globs))
    except (OSError, UnicodeError):
        return [Finding(relative, 1, "unscanned-content", "<redacted>")]
    return findings
def _is_archive(name: str) -> bool: return name.lower().endswith(_ARCHIVE_SUFFIXES)
def _is_nested_archive(name: str) -> bool: return name.lower().endswith(_NESTED_ARCHIVES)
def _looks_like_archive(name: str) -> bool: return name.lower().endswith(_ARCHIVE_LIKE)
def _safe_member(name: str) -> bool:
    clean = name.rstrip("/"); parts = clean.split("/")
    return bool(clean) and not clean.startswith("/") and "\\" not in clean and "\0" not in clean and not re.match(r"^[A-Za-z]:", clean) and all(part not in {"", ".", ".."} for part in parts)
def _unscanned(label: str) -> Finding: return Finding(label, 1, "unscanned-content", "<redacted>")
def _claim_member(size: int, budget: list[int]) -> bool:
    if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES or budget[0] >= MAX_ARCHIVE_MEMBERS or budget[1] + size > MAX_ARCHIVE_BYTES: return False
    budget[0] += 1; budget[1] += size; return True
class _MemberStream:
    def __init__(self, stream: IO[bytes], expected: int): self.stream, self.expected, self.seen = stream, expected, 0
    def read(self, size: int = -1) -> bytes:
        value = self.stream.read(size); self.seen += len(value)
        if self.seen > self.expected: raise ValueError
        return value
    def complete(self) -> None:
        if self.seen != self.expected: raise ValueError
def _scan_plain_member(stream: IO[bytes], size: int, name: str, label: str, exact: list[dict[str, str]], globs: list[dict[str, str]]) -> list[Finding]:
    bounded = _MemberStream(stream, size)
    if Path(name).suffix.lower() in _ALLOWED_BINARY_SUFFIXES:
        while bounded.read(CHUNK_BYTES): pass
        found: list[Finding] = []
    else: found = _scan_stream(bounded, label, exact, globs)  # type: ignore[arg-type]
    if not any(item.rule_id == "unscanned-content" for item in found): bounded.complete()
    return found
def _scan_nested(stream: IO[bytes], size: int, name: str, label: str, exact: list[dict[str, str]], globs: list[dict[str, str]], depth: int, budget: list[int]) -> list[Finding]:
    if depth + 1 >= MAX_ARCHIVE_DEPTH or size > MAX_NESTED_ARCHIVE_BYTES: return [_unscanned(label)]
    bounded = _MemberStream(stream, size)
    with tempfile.SpooledTemporaryFile(max_size=1_048_576, mode="w+b") as nested:
        while chunk := bounded.read(CHUNK_BYTES): nested.write(chunk)
        bounded.complete(); nested.seek(0)
        return _scan_archive(nested, name, label, exact, globs, depth + 1, budget)
def _scan_archive(source: Any, name: str, relative: str, exact: list[dict[str, str]], globs: list[dict[str, str]], depth: int = 0, budget: list[int] | None = None) -> list[Finding]:
    found: list[Finding] = []; budget = [0, 0] if budget is None else budget
    try:
        if name.lower().endswith((".zip", ".whl")):
            with zipfile.ZipFile(source) as archive:
                zip_members = archive.infolist()
                if len(zip_members) + budget[0] > MAX_ARCHIVE_MEMBERS: raise ValueError
                for zip_member in zip_members:
                    raw_name = zip_member.filename; label = f"{relative}!{raw_name}"; mode = zip_member.external_attr >> 16
                    if not _safe_member(raw_name): found.append(_unscanned(f"{relative}!<unsafe-member>")); continue
                    if zip_member.is_dir(): continue
                    if not _claim_member(zip_member.file_size, budget) or zip_member.flag_bits & 1 or stat.S_ISLNK(mode) or (zip_member.file_size and zip_member.file_size > max(1, zip_member.compress_size) * MAX_COMPRESSION_RATIO): found.append(_unscanned(label)); continue
                    if _looks_like_archive(raw_name) and not _is_nested_archive(raw_name): found.append(_unscanned(label)); continue
                    try:
                        with archive.open(zip_member) as stream:
                            items = _scan_nested(stream, zip_member.file_size, raw_name, label, exact, globs, depth, budget) if _is_nested_archive(raw_name) else _scan_plain_member(stream, zip_member.file_size, raw_name, label, exact, globs)
                        found.extend(items)
                    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile): found.append(_unscanned(label))
        else:
            arguments = {"name": source} if isinstance(source, (str, Path)) else {"fileobj": source}
            with tarfile.open(mode="r:*", **arguments) as archive:
                tar_members = archive.getmembers()
                if len(tar_members) + budget[0] > MAX_ARCHIVE_MEMBERS: raise ValueError
                for tar_member in tar_members:
                    raw_name = tar_member.name; label = f"{relative}!{raw_name}"
                    if not _safe_member(raw_name): found.append(_unscanned(f"{relative}!<unsafe-member>")); continue
                    if tar_member.isdir(): continue
                    if not tar_member.isfile() or not _claim_member(tar_member.size, budget): found.append(_unscanned(label)); continue
                    if _looks_like_archive(raw_name) and not _is_nested_archive(raw_name): found.append(_unscanned(label)); continue
                    try:
                        tar_stream = archive.extractfile(tar_member)
                        if tar_stream is None: raise OSError
                        with tar_stream: items = _scan_nested(tar_stream, tar_member.size, raw_name, label, exact, globs, depth, budget) if _is_nested_archive(raw_name) else _scan_plain_member(tar_stream, tar_member.size, raw_name, label, exact, globs)
                        found.extend(items)
                    except (OSError, RuntimeError, ValueError, tarfile.TarError): found.append(_unscanned(label))
    except (OSError, RuntimeError, ValueError, tarfile.TarError, zipfile.BadZipFile): return [_unscanned(relative)]
    return found
def _deployment_finding(path: Path, relative: str) -> list[Finding]:
    if Path(relative).name.lower() not in {"deployment.yaml", "deployment.yml"}:
        return []
    try:
        raw = path.read_bytes(); text = raw.decode("utf-8") if len(raw) <= MAX_POLICY_BYTES else ""
    except (OSError, UnicodeError):
        return []
    required = (r"(?m)^services:\s*$", r"(?m)^\s+image:\s*\S+", r"(?m)^\s+ports:\s*(?:$|\[)"); return [Finding(relative, 1, "deployment-manifest", "<redacted>")] if all(re.search(item, text) for item in required) else []
def _scan_path(path: Path, relative: str, exact: list[dict[str, str]], globs: list[dict[str, str]]) -> list[Finding]:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            return [Finding(relative, 1, "unscanned-content", "<redacted>")]
        if path.suffix.lower() in _ALLOWED_BINARY_SUFFIXES:
            return []
        if _is_archive(relative):
            return _scan_archive(path, relative, relative, exact, globs)
        with path.open("rb") as stream:
            return _scan_stream(stream, relative, exact, globs) + _deployment_finding(path, relative)
    except OSError:
        return [Finding(relative, 1, "unscanned-content", "<redacted>")]
def scan(root: str | Path, *, artifacts: Sequence[str | Path] = (), deny_policy: str | Path | None = None) -> tuple[Finding, ...]:
    return _scan(root, artifacts, deny_policy, None)
def _scan(root: str | Path, artifacts: Sequence[str | Path], deny_policy: str | Path | None, exclude: Path | None) -> tuple[Finding, ...]:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ValueError("root must be a directory")
    root_path = root_path.resolve()
    policy_path = Path(deny_policy).resolve() if deny_policy is not None else None
    exact, globs = _load_policy(policy_path)
    tracked = _git_files(root_path)
    files = _tree_files(root_path) if tracked is None else tracked
    hidden: Iterable[Path] = root_path.iterdir() if tracked is None else {root_path / path.relative_to(root_path).parts[0] for path in tracked}
    files.extend(_artifact_files(root_path, artifacts))
    findings: list[Finding] = []
    for child in sorted(hidden, key=lambda item: item.name):
        if child.name.startswith(".") and child.name not in _ALLOWED_HIDDEN and child.is_dir() and not child.is_symlink():
            findings.append(Finding(child.name + "/", 1, "unknown-hidden-config", "<redacted>"))
    for path in sorted(set(files), key=lambda item: item.relative_to(root_path).as_posix()):
        try:
            relative = path.relative_to(root_path).as_posix()
            resolved = path.resolve()
        except (OSError, ValueError):
            findings.append(Finding("<invalid-path>", 1, "unscanned-content", "<redacted>"))
            continue
        if resolved not in {policy_path, exclude}:
            findings.extend(_scan_path(path, relative, exact, globs))
    return tuple(sorted(set(findings)))
def _report(findings: tuple[Finding, ...]) -> bytes:
    return _canonical_json({"findings": [asdict(finding) for finding in findings], "schema_version": 1, "tool": "provider-neutrality"})
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--deny-policy")
    parser.add_argument("--report-json")
    args = parser.parse_args(argv)
    try:
        report_path = Path(args.report_json).resolve() if args.report_json else None
        findings = _scan(args.root, args.artifact, args.deny_policy, report_path)
        if report_path:
            report_path.write_bytes(_report(findings))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 1 if findings else 0
if __name__ == "__main__":
    raise SystemExit(main())
