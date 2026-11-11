import errno
import os
from pathlib import Path
import sys

import pytest

INSTALLER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INSTALLER))
sys.path.insert(0, str(INSTALLER / 'payload'))

from vault_transfer import copy_new


def _copy_fixture(tmp_path, monkeypatch=None, *, link_error=None, rename_result=False, check_mount=None):
    source = tmp_path / 'source.txt'
    source.write_text('Workspace check 7294')
    target_dir = tmp_path / 'destination'
    target_dir.mkdir()
    source_fd = os.open(source, os.O_RDONLY)
    try:
        if link_error is not None:
            def fail_link(*args, **kwargs):
                raise OSError(link_error, os.strerror(link_error))
            monkeypatch.setattr('vault_transfer.os.link', fail_link)
        if monkeypatch is not None:
            def fake_rename(temp, name, dir_fd):
                if rename_result:
                    os.rename(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                return rename_result
            monkeypatch.setattr('vault_transfer._rename_exclusive', fake_rename)
        dest_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            copy_new(source_fd, dest_fd, 'workspace-check.txt', check_mount)
        finally:
            os.close(dest_fd)
    finally:
        os.close(source_fd)
    return target_dir


def test_copy_new_falls_back_when_mounted_filesystem_rejects_hardlinks(tmp_path, monkeypatch):
    target_dir = _copy_fixture(tmp_path, monkeypatch, link_error=errno.EOPNOTSUPP)
    assert (target_dir / 'workspace-check.txt').read_text() == 'Workspace check 7294'
    assert sorted(p.name for p in target_dir.iterdir()) == ['workspace-check.txt']


def test_copy_new_uses_exclusive_rename_when_available(tmp_path, monkeypatch):
    target_dir = _copy_fixture(tmp_path, monkeypatch, link_error=errno.ENOTSUP,
                               rename_result=True)
    assert (target_dir / 'workspace-check.txt').read_text() == 'Workspace check 7294'
    assert sorted(p.name for p in target_dir.iterdir()) == ['workspace-check.txt']


def test_copy_new_never_replaces_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    source.write_text('new content')
    target_dir = tmp_path / 'destination'
    target_dir.mkdir()
    destination = target_dir / 'workspace-check.txt'
    destination.write_text('keep existing content')
    source_fd = os.open(source, os.O_RDONLY)
    dest_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        monkeypatch.setattr('vault_transfer._rename_exclusive',
                            lambda *args: pytest.fail('must not retry a destination collision'))
        with pytest.raises(FileExistsError):
            copy_new(source_fd, dest_fd, destination.name)
    finally:
        os.close(source_fd)
        os.close(dest_fd)
    assert destination.read_text() == 'keep existing content'
    assert sorted(p.name for p in target_dir.iterdir()) == ['workspace-check.txt']


def test_fallback_removes_partial_destination_on_failure(tmp_path, monkeypatch):
    calls = 0
    def check_mount():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError('vault mount changed during fallback copy')
    with pytest.raises(OSError, match='vault mount changed'):
        _copy_fixture(tmp_path, monkeypatch, link_error=errno.ENOTSUP,
                      check_mount=check_mount)
    target_dir = tmp_path / 'destination'
    assert sorted(p.name for p in target_dir.iterdir()) == []

