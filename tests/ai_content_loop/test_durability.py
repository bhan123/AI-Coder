from pathlib import Path

from ai_content_loop import durability


def test_fsync_directory_uses_directory_descriptor_on_posix(
    tmp_path: Path, monkeypatch
):
    calls = []
    monkeypatch.setattr(durability, "_IS_WINDOWS", False)
    monkeypatch.setattr(
        durability.os,
        "open",
        lambda path, flags: calls.append(("open", Path(path), flags)) or 17,
    )
    monkeypatch.setattr(
        durability.os,
        "fsync",
        lambda descriptor: calls.append(("fsync", descriptor)),
    )
    monkeypatch.setattr(
        durability.os,
        "close",
        lambda descriptor: calls.append(("close", descriptor)),
    )

    durability.fsync_directory(tmp_path)

    assert calls[0][0:2] == ("open", tmp_path)
    assert calls[1:] == [("fsync", 17), ("close", 17)]
