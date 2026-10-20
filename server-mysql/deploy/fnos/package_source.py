"""Package only reproducible build inputs, excluding credentials and clients."""
import argparse
import hashlib
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def package(output):
    entries = []
    for directory in ('server-mysql', 'web', 'datatable_json'):
        for path in (ROOT / directory).rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if any(part in ('node_modules', 'dist', '.git', '__pycache__', 'logs', 'client-patches') for part in relative.parts):
                continue
            if path.name == '.env' or path.suffix.lower() in ('.exe', '.dll', '.log', '.bak', '.pyc'):
                continue
            if path.suffix == '' and path.name not in ('Dockerfile', 'SkillLogicConfig', 'mhqserver', 'gm-api'):
                continue
            if path.name in ('mhqserver', 'gm-api'):
                continue
            entries.append(path)
    entries += [ROOT / 'tools/prepare_config_yaml.py', ROOT / '.dockerignore']
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for path in sorted(set(entries)):
            archive.add(path, arcname='source/' + path.relative_to(ROOT).as_posix(), recursive=False)
    print(f'{output.name}: {len(entries)} source files, {output.stat().st_size} bytes, sha256={hashlib.sha256(output.read_bytes()).hexdigest()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    package(parser.parse_args().output)
