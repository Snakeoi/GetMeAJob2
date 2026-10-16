import json
import subprocess
from pathlib import Path

import pytest

from getmeajob.config import DEFAULT_SEARCH_PROFILE
from getmeajob.evaluation import CodexEvaluator


@pytest.mark.parametrize('configured,explicit,expected', [
    (None, None, None), ('account-model', None, 'account-model'),
    ('account-model', 'override-model', 'override-model'),
])
def test_model_selection(monkeypatch, configured, explicit, expected):
    monkeypatch.delenv('GETMEAJOB_CODEX_MODEL', raising=False)
    if configured:
        monkeypatch.setenv('GETMEAJOB_CODEX_MODEL', configured)

    def run(command, **kwargs):
        if expected:
            assert command[command.index('--model') + 1] == expected
        else:
            assert '--model' not in command
        output = Path(command[command.index('--output-last-message') + 1])
        output.write_text(json.dumps({'recommendation': 'sprawdź', 'rationale': 'Test'}))
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(subprocess, 'run', run)
    result = CodexEvaluator(model=explicit).evaluate({'remote_mode': 'remote'}, DEFAULT_SEARCH_PROFILE, {'facts': []})
    assert result['rationale'] == 'Test'


@pytest.mark.parametrize('error_line', ['', 'ERROR: Unsupported model'])
def test_error_excludes_echoed_candidate_prompt(monkeypatch, error_line):
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: subprocess.CompletedProcess(
        command, 1, 'PRIVATE PROFILE', 'PRIVATE PROFILE\n' + error_line,
    ))
    with pytest.raises(RuntimeError) as error:
        CodexEvaluator().evaluate({}, DEFAULT_SEARCH_PROFILE, {'facts': []})
    assert 'PRIVATE PROFILE' not in str(error.value)
    if error_line:
        assert error_line in str(error.value)


def test_executable_override(monkeypatch):
    monkeypatch.setenv('GETMEAJOB_CODEX_EXECUTABLE', '/custom/codex')
    assert CodexEvaluator().executable == '/custom/codex'
    assert CodexEvaluator(executable='/explicit/codex').executable == '/explicit/codex'


def test_bundled_executable_and_path_fallback(monkeypatch):
    monkeypatch.delenv('GETMEAJOB_CODEX_EXECUTABLE', raising=False)
    monkeypatch.setattr(Path, 'is_file', lambda path: str(path) == '/Applications/ChatGPT.app/Contents/Resources/codex')
    monkeypatch.setattr('os.access', lambda *args: True)
    assert CodexEvaluator().executable == '/Applications/ChatGPT.app/Contents/Resources/codex'
    monkeypatch.setattr(Path, 'is_file', lambda path: False)
    assert CodexEvaluator().executable == 'codex'
