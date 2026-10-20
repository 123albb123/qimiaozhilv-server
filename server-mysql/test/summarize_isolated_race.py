"""Require real race test completion and explicit coverage of formerly skipped tests."""
import argparse
import hashlib
import json
from pathlib import Path


def read_text(path):
    raw = path.read_bytes()
    return raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--required', type=Path, required=True)
    parser.add_argument('--game-log', type=Path, required=True)
    parser.add_argument('--exit-code', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = read_text(args.events)
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    states = {e['Test']: e['Action'] for e in events
              if 'Test' in e and e['Action'] in ('pass', 'fail', 'skip')}
    required = sorted(set(read_text(args.required).split()))
    if len(required) != 57 or any(not name.startswith('Test') for name in required):
        raise ValueError('Expected the fixed list of 57 previously skipped tests')
    root = {name: state for name, state in states.items() if '/' not in name}
    package = [e['Action'] for e in events if 'Test' not in e and e['Action'] in ('pass', 'fail')]
    problems = []
    if not package or package[-1] != 'pass':
        problems.append('package did not complete successfully')
    if read_text(args.exit_code).strip() != '0':
        problems.append('test process exit was not zero')
    if any(state != 'pass' for state in root.values()):
        problems.append('root suite contains a failed or skipped test')
    missing = [name for name in required if root.get(name) != 'pass']
    if missing:
        problems.append('formerly skipped tests did not all pass')
    if 'WARNING: DATA RACE' in raw + read_text(args.game_log):
        problems.append('race detector reported a race')
    summary = {
        'package': 'mhqserver',
        'rootPassed': sum(state == 'pass' for state in root.values()),
        'rootFailed': sum(state == 'fail' for state in root.values()),
        'rootSkipped': sum(state == 'skip' for state in root.values()),
        'requiredCount': len(required),
        'requiredPassed': len(required) - len(missing),
        'missingRequired': missing,
        'requiredTests': {name: root.get(name, 'not executed') for name in required},
        'eventsSha256': hashlib.sha256(args.events.read_bytes()).hexdigest(),
        'gameLogSha256': hashlib.sha256(args.game_log.read_bytes()).hexdigest(),
        'problems': problems,
    }
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ('requiredTests', 'eventsSha256', 'gameLogSha256')}))
    raise SystemExit(bool(problems))


if __name__ == '__main__':
    main()
