"""Media Import: файлы, папки, фильтрация, скрытые файлы."""
from core.media_import import collect_video_files


def test_collect_from_folder(tmp_path):
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.MOV").touch()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.mkv").touch()
    (tmp_path / "readme.txt").touch()
    (tmp_path / ".hidden.mp4").touch()
    files = collect_video_files([tmp_path])
    names = [f.name for f in files]
    assert names == sorted(["a.mp4", "b.MOV", "c.mkv"])


def test_collect_skips_hidden_dirs(tmp_path):
    """Файлы в скрытых папках (.videoeditor и т.п.) не попадают в импорт."""
    (tmp_path / "a.mp4").touch()
    hidden = tmp_path / ".videoeditor" / "cache"
    hidden.mkdir(parents=True)
    (hidden / "tmp.mp4").touch()
    files = collect_video_files([tmp_path])
    assert [f.name for f in files] == ["a.mp4"]


def test_collect_explicit_files_and_dedup(tmp_path):
    f = tmp_path / "a.mp4"
    f.touch()
    files = collect_video_files([f, f, tmp_path])
    assert len(files) == 1


def test_collect_nonexistent_and_wrong_type(tmp_path):
    assert collect_video_files([tmp_path / "nope.mp4"]) == []
    txt = tmp_path / "x.txt"
    txt.touch()
    assert collect_video_files([txt]) == []


def test_collect_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "v.mp4").touch()
    assert len(collect_video_files(["~/v.mp4"])) == 1
