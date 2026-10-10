"""Bound external ingestion and install validated files with rollback on failure."""

from __future__ import annotations

import os
import stat
import struct
import zipfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, TextIO


@dataclass(frozen=True)
class IngestionLimits:
    download_bytes: int = 256 * 1024 * 1024
    expanded_bytes: int = 2 * 1024 * 1024 * 1024
    member_bytes: int = 1024 * 1024 * 1024
    members: int = 512
    compression_ratio: int = 200
    rows: int = 10_000_000


DEFAULT_LIMITS = IngestionLimits()


def bounded_text_lines(source: TextIO, max_chars: int = 65_536) -> Iterable[str]:
    """Refuse an oversized physical line before CSV's iterator materializes it."""
    while line := source.readline(max_chars + 1):
        if len(line) > max_chars:
            raise RuntimeError("Source line exceeds character budget")
        yield line


@contextmanager
def bounded_zip(source, limits: IngestionLimits):
    """Check ZIP directory size/count before ZipFile materializes its members.

    Governed archives fit the ordinary ZIP format. Multi-disk and ZIP64 inputs
    exceed this contract and are refused rather than parsed speculatively.
    """
    stream = source.open("rb") if isinstance(source, Path) else source
    try:
        stream.seek(0, 2)
        size = stream.tell()
        if size > limits.download_bytes:
            raise RuntimeError("Archive exceeds compressed byte budget")
        stream.seek(max(0, size - 65_557))
        tail = stream.read(65_557)
        offset = tail.rfind(b"PK\x05\x06")
        if offset < 0 or len(tail) - offset < 22:
            raise RuntimeError("Archive has no valid ZIP directory")
        (
            _,
            disk,
            directory_disk,
            disk_count,
            count,
            directory_size,
            directory_offset,
            comment_size,
        ) = struct.unpack("<4s4H2IH", tail[offset : offset + 22])
        if disk or directory_disk or disk_count != count or len(tail) - offset != 22 + comment_size:
            raise RuntimeError("Unsupported ZIP directory")
        if count > limits.members or directory_size > 2 * 1024 * 1024:
            raise RuntimeError("Archive exceeds directory member or byte budget")
        if offset >= 20 and tail[offset - 20 : offset - 16] == b"PK\x06\x07":
            raise RuntimeError("ZIP64 archives exceed the supported archive contract")
        if directory_offset + directory_size > size - 22 - comment_size:
            raise RuntimeError("Invalid ZIP directory offset")
        stream.seek(directory_offset)
        directory = stream.read(directory_size)
        position = 0
        actual_count = 0
        while position < len(directory):
            if (
                directory[position : position + 4] != b"PK\x01\x02"
                or len(directory) - position < 46
            ):
                raise RuntimeError("Invalid ZIP directory entry")
            name_size, extra_size, entry_comment_size = struct.unpack(
                "<3H", directory[position + 28 : position + 34]
            )
            position += 46 + name_size + extra_size + entry_comment_size
            actual_count += 1
            if actual_count > limits.members:
                raise RuntimeError("Archive exceeds directory member budget")
        if position != len(directory) or actual_count != count:
            raise RuntimeError("ZIP directory count or size mismatch")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            yield archive
    finally:
        if isinstance(source, Path):
            stream.close()


def copy_bounded(chunks: Iterable[bytes], output: BinaryIO, limit: int) -> int:
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise RuntimeError("Upstream download exceeds byte budget")
        output.write(chunk)
    return total


def validate_archive(archive: zipfile.ZipFile, limits: IngestionLimits) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > limits.members:
        raise RuntimeError("Archive exceeds member budget")
    total = 0
    names: set[str] = set()
    for member in members:
        mode = member.external_attr >> 16
        if member.filename in names or stat.S_ISLNK(mode):
            raise RuntimeError("Archive has duplicate or symlink member")
        names.add(member.filename)
        total += member.file_size
        if member.file_size > limits.member_bytes or total > limits.expanded_bytes:
            raise RuntimeError("Archive exceeds expansion budget")
        if member.file_size > max(1, member.compress_size) * limits.compression_ratio:
            raise RuntimeError("Archive exceeds compression ratio budget")
    return members


def install_staged_files(staging: Path, target: Path, names: Iterable[str]) -> None:
    """Replace each file atomically; restore the prior set if any replacement fails.

    Offline ingestion requires exclusive access. This is rollback protection, not
    a multi-file transaction for concurrent readers or machine power failure.
    """
    target.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ingestion-backup-", dir=target.parent) as backup_dir:
        backup = Path(backup_dir)
        saved: list[str] = []
        installed: list[str] = []
        try:
            for name in names:
                destination = target / name
                if destination.exists() or destination.is_symlink():
                    os.replace(destination, backup / name)
                    saved.append(name)
                os.replace(staging / name, destination)
                installed.append(name)
        except BaseException:
            for name in reversed(installed):
                (target / name).unlink()
            for name in reversed(saved):
                os.replace(backup / name, target / name)
            raise
