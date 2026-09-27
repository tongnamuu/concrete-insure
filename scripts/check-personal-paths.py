#!/usr/bin/env python3
"""Reject personal filesystem paths in the Git index, without echoing them."""
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

SEP = r'(?:/|\\)+'
USER = r'[\w.@-]+'
PATTERNS = (
    re.compile(SEP + r'(?:Users|home)' + SEP + USER),
    re.compile(r'(?i:[a-z]:' + SEP + r'(?:Users|Documents and Settings)' + SEP + USER + ')'),
    re.compile(SEP + r'root' + SEP),
    re.compile(SEP + r'(?:private' + SEP + r')?var' + SEP + r'folders' + SEP + USER),
)


def contains_personal_path(value):
    # Accept Windows separators, escaped JSON separators and URL-encoded paths.
    variants = [value, unquote(value)]
    home = str(Path.home()).replace('\\', '/').rstrip('/')
    for text in variants:
        normalized = text.replace('\\', '/')
        if any(pattern.search(text) for pattern in PATTERNS):
            return True
        if home and home != '/' and (normalized == home or home + '/' in normalized):
            return True
    return False


def unsafe_lines(blob):
    texts = [blob.decode('utf-8', errors='replace')]
    if b'\x00' in blob or blob.startswith((b'\xff\xfe', b'\xfe\xff')):
        texts += [blob.decode(codec, errors='replace') for codec in ('utf-16-le', 'utf-16-be')]
    return sorted({number for text in texts for number, line in enumerate(text.splitlines(), 1)
                   if contains_personal_path(line)})


def git(*args, input=None):
    return subprocess.run(['git', *args], input=input, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=60).stdout


def staged_files():
    entries = []
    for record in git('ls-files', '--stage', '-z').split(b'\x00'):
        if not record:
            continue
        metadata, filename = record.split(b'\t', 1)
        mode, oid, stage = metadata.split()
        if stage != b'0' or mode not in (b'100644', b'100755', b'120000'):
            raise ValueError('Unmerged or unsupported index entry')
        entries.append((filename.decode('utf-8', errors='replace'), oid))
    output = git('cat-file', '--batch', input=b''.join(oid + b'\n' for _, oid in entries))
    offset = 0
    for filename, oid in entries:
        header_end = output.index(b'\n', offset)
        actual_oid, kind, length = output[offset:header_end].split()
        size = int(length)
        start = header_end + 1
        if actual_oid != oid or kind != b'blob' or len(output) < start + size + 1:
            raise ValueError('Invalid Git object')
        yield filename, output[start:start + size]
        offset = start + size + 1


def main():
    try:
        problems = []
        count = 0
        for filename, blob in staged_files():
            count += 1
            unsafe_name = contains_personal_path('/' + filename)
            lines = unsafe_lines(blob)
            if unsafe_name or lines:
                # Never repeat a personal path, including one in the filename.
                name = '[redacted filename]' if unsafe_name else ascii(filename)
                location = 'filename' if unsafe_name else 'lines ' + ', '.join(map(str, lines[:10]))
                problems.append(f'  {name}: {location}')
        if problems:
            print('Personal path check FAILED. Replace local paths with project-relative paths or configuration.', file=sys.stderr)
            print('\n'.join(problems[:50]), file=sys.stderr)
            print('Stage the corrected files and commit again. Do not bypass the hook.', file=sys.stderr)
            return 1
        print(f'Personal path check passed ({count} indexed files).')
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Personal path check could not inspect the Git index; commit blocked.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
