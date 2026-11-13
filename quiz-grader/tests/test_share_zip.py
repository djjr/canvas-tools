from zipfile import ZipFile

from make_share_zip import build_archive

PREFIX = 'canvas-quiz-grader/'


def test_share_zip_includes_launchers_and_excludes_private_data(tmp_path):
    path = build_archive(destination=tmp_path / 'share.zip')
    with ZipFile(path) as archive:
        infos = {i.filename: i for i in archive.infolist()}
        names = set(infos)
        assert PREFIX + 'Start Margin.command' in names
        assert PREFIX + 'Start Margin.bat' in names
        assert (infos[PREFIX + 'Start Margin.command'].external_attr >> 16) & 0o111
        assert not (infos[PREFIX + 'app.py'].external_attr >> 16) & 0o111
        assert b'\r\n' in archive.read(PREFIX + 'Start Margin.bat')
        assert b'CANVAS_TOKEN=\n' in archive.read(PREFIX + '.env.example')
    assert PREFIX + '.env' not in names
    assert not any(n.startswith((PREFIX + 'instance/', PREFIX + '.venv/', PREFIX + 'dist/')) for n in names)
