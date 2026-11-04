"""Verify the packaged evidence against its SHA-256 manifest (no network)."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'evidence-sha256.json').read_text())
    expected = {entry['file']: entry['sha256'] for entry in manifest}
    actual = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*')
        if p.is_file() and p.name != 'evidence-sha256.json'
        and '__pycache__' not in p.parts and p.suffix != '.pyc'
    }
    failures = sorted(name for name in expected.keys() | actual.keys()
                      if expected.get(name) != actual.get(name))
    if failures:
        raise SystemExit('Missing, changed or unexpected evidence:\n' + '\n'.join(failures))
    print(f'{len(expected)} evidence files verified (SHA-256).')


if __name__ == '__main__':
    main()
