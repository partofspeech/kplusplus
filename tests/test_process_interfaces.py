"""Real subprocess protocols, including Cyrillic; no browser or source login."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_gui_worker_reads_utf8_and_returns_readable_error(tmp_path):
    payload = {
        'config': {'scraper': {'sources': ['неизвестный-источник']}, 'search': {'query': 'Федеральный закон'}},
        'runtime_dir': str(tmp_path / 'Служебная папка'),
    }
    environment = {**os.environ, 'PYTHONUTF8': '0'}
    process = subprocess.run([sys.executable, '-X', 'utf8', '-u', '-m', 'interfaces.web.worker'],
                             input=json.dumps(payload, ensure_ascii=False) + '\n',
                             cwd=ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert process.returncode == 0, process.stderr
    event = json.loads(process.stdout)
    assert event['type'] == 'error'
    assert 'неизвестный-источник' in event['message']
    assert not (tmp_path / 'Служебная папка').exists()


def test_cli_handles_cyrillic_config_without_source_credentials(tmp_path):
    config_path = tmp_path / 'Настройки для проверки.toml'
    output = tmp_path / 'Судебные акты'
    config_path.write_text('[scraper]\nsources=["sudact"]\n'
                           '[sources.sudact]\nname="Судакт.ру"\n'
                           '[export]\ndirectory=' + json.dumps(str(output), ensure_ascii=False) + '\n', encoding='utf-8')
    process = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'interfaces.cli', '--config', str(config_path)],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert process.returncode == 0, process.stderr
    assert 'Судакт.ру' in process.stderr
    assert 'сохранено 0' in process.stdout
    assert str(output) in process.stdout
