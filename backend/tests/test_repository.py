from pathlib import Path

from app.services.repository import discover_files


def test_discovery_excludes_secrets_and_node_modules(tmp_path: Path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'a.ts').write_text('export const a = 1')
    (tmp_path / 'lambdaBackend').mkdir()
    (tmp_path / 'lambdaBackend' / 'handler.mjs').write_text('export const handler = async () => {}')
    (tmp_path / '.env').write_text('TOKEN=secret')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'bad.js').write_text('bad')
    found = {p.relative_to(tmp_path).as_posix() for p in discover_files(tmp_path)}
    assert 'src/a.ts' in found
    assert 'lambdaBackend/handler.mjs' in found
    assert '.env' not in found
    assert 'node_modules/bad.js' not in found
