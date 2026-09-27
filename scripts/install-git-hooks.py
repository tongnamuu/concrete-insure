#!/usr/bin/env python3
"""Install this repository's mandatory pre-commit check without global changes."""
from pathlib import Path
import subprocess
import sys


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout.strip()


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('Run from the project root.')
        configured = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], capture_output=True, text=True)
        if configured.returncode not in (0, 1):
            raise ValueError('Cannot read existing hook configuration.')
        if configured.returncode == 0 and configured.stdout.strip() != '.githooks':
            raise ValueError('A different hooksPath is configured; integrate the existing hooks first.')
        if configured.returncode == 1 and Path(git('rev-parse', '--git-path', 'hooks/pre-commit')).exists():
            raise ValueError('An existing pre-commit hook must be integrated first.')
        hook = root / '.githooks' / 'pre-commit'
        if not hook.is_file():
            raise ValueError('The project pre-commit hook is missing.')
        hook.chmod(hook.stat().st_mode | 0o111)
        git('config', '--local', 'core.hooksPath', '.githooks')
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print('Could not install the project Git hooks.', file=sys.stderr)
        return 1
    print('Installed: every normal git commit checks the full index for personal paths.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
