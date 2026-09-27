"""Exercise the actual pre-commit hook in isolated repositories, never this repo."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import quote

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('personal_paths', PROJECT / 'scripts/check-personal-paths.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def absolute(*parts):
    return '/' + '/'.join(parts)


MAC = absolute('Users', 'fixture-person', 'work', 'notes.txt')
WINDOWS = chr(92).join(['C:', 'Users', 'fixture-person', 'notes.txt'])


def command(repo, *args, check=True):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(args, cwd=repo, env=env, capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path):
    command(tmp_path, 'git', 'init', '--quiet')
    command(tmp_path, 'git', 'config', 'user.name', 'Test')
    command(tmp_path, 'git', 'config', 'user.email', 'test@example.invalid')
    shutil.copytree(PROJECT / '.githooks', tmp_path / '.githooks')
    (tmp_path / 'scripts').mkdir()
    for name in ('check-personal-paths.py', 'install-git-hooks.py'):
        shutil.copy2(PROJECT / 'scripts' / name, tmp_path / 'scripts' / name)
    command(tmp_path, sys.executable, 'scripts/install-git-hooks.py')
    return tmp_path


@pytest.mark.parametrize('content', [
    MAC.encode(),
    absolute('home', 'fixture-person', 'project').encode(),
    absolute('root', 'private', 'notes').encode(),
    WINDOWS.encode(),
    json.dumps({'path': WINDOWS}).encode(),
    json.dumps({'path': MAC}).replace('/', '\\/').encode(),
    quote(MAC, safe='').encode(),
    absolute('private', 'var', 'folders', 'xx', 'fixture', 'T', 'note').encode(),
    MAC.encode('utf-16-le'),
    MAC.encode('utf-16-be'),
])
def test_actual_commit_blocks_index_even_if_worktree_is_clean(repo, content):
    file = repo / 'notes with spaces.md'
    file.write_bytes(content)
    command(repo, 'git', 'add', '.')
    file.write_text('This unstaged correction must not hide the staged path.\n')
    result = command(repo, 'git', 'commit', '-m', 'Add notes', check=False)
    assert result.returncode != 0
    assert 'Personal path check FAILED' in result.stderr
    assert 'fixture-person' not in result.stderr and MAC not in result.stderr
    assert command(repo, 'git', 'rev-parse', '--verify', 'HEAD', check=False).returncode != 0
    command(repo, 'git', 'add', '.')
    result = command(repo, 'git', 'commit', '-m', 'Add safe notes')
    assert 'Personal path check passed' in result.stdout + result.stderr
    assert command(repo, 'git', 'rev-list', '--count', 'HEAD').stdout.strip() == '1'


def test_all_indexed_files_checked_even_when_only_other_file_changes(repo):
    (repo / 'unrelated.md').write_text('safe')
    command(repo, 'git', 'add', '.')
    command(repo, 'git', 'commit', '-m', 'Initial safe files')
    # Seed an existing blob in the index without creating a bad commit.
    (repo / 'legacy.md').write_text(MAC)
    command(repo, 'git', 'add', 'legacy.md')
    (repo / 'unrelated.md').write_text('updated')
    command(repo, 'git', 'add', 'unrelated.md')
    result = command(repo, sys.executable, 'scripts/check-personal-paths.py', check=False)
    assert result.returncode == 1 and 'legacy.md' in result.stderr
    command(repo, 'git', 'rm', '--cached', 'legacy.md')
    command(repo, 'git', 'commit', '-m', 'Update safe file')


def test_symlink_target_is_checked_without_following_it(repo):
    (repo / 'shortcut').symlink_to(MAC)
    command(repo, 'git', 'add', '.')
    result = command(repo, 'git', 'commit', '-m', 'Add link', check=False)
    assert result.returncode != 0 and 'shortcut' in result.stderr
    assert MAC not in result.stderr


def test_unsafe_filename_is_redacted(repo):
    relative = Path('Users') / 'fixture-person' / 'notes.txt'
    (repo / relative).parent.mkdir(parents=True)
    (repo / relative).write_text('safe content')
    command(repo, 'git', 'add', '.')
    result = command(repo, 'git', 'commit', '-m', 'Add notes', check=False)
    assert result.returncode != 0 and '[redacted filename]' in result.stderr
    assert 'fixture-person' not in result.stderr


def test_installation_is_local_idempotent_and_preserves_other_hooks(repo):
    command(repo, sys.executable, 'scripts/install-git-hooks.py')
    assert command(repo, 'git', 'config', '--local', '--get', 'core.hooksPath').stdout.strip() == '.githooks'
    command(repo, 'git', 'config', '--local', 'core.hooksPath', 'custom-hooks')
    result = command(repo, sys.executable, 'scripts/install-git-hooks.py', check=False)
    assert result.returncode == 1
    assert command(repo, 'git', 'config', '--local', '--get', 'core.hooksPath').stdout.strip() == 'custom-hooks'


def test_checker_fails_closed_outside_repository(tmp_path):
    result = command(tmp_path, sys.executable, str(PROJECT / 'scripts/check-personal-paths.py'), check=False)
    assert result.returncode == 2 and 'commit blocked' in result.stderr


def test_relative_paths_and_placeholders_are_allowed():
    for text in ('docs/logging.md', '${DATA_DIR}/documents', './scripts/check-personal-paths.py'):
        assert not CHECK.contains_personal_path(text)
