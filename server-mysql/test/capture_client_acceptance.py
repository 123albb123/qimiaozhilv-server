"""Capture read-only GM state to corroborate an actual client acceptance step.

The only POSTs are login/logout for a separate in-memory GM session. This does
not play the game, grant prerequisites, or turn a protocol check into UI proof.
"""
import argparse
import datetime
import http.cookiejar
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--base', default='http://192.168.1.22:8897')
    parser.add_argument('--player', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.base != 'http://192.168.1.22:8897' or args.player < 1:
        raise SystemExit('This evidence collector is scoped to the authorized NAS.')
    env = {}
    for line in args.credentials.read_text(encoding='utf-8-sig').splitlines():
        key, sep, value = line.partition('=')
        if sep:
            env[key.strip()] = value.strip().strip('"\'')
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPCookieProcessor(jar))

    def api(path, data=None):
        headers = {'Content-Type': 'application/json', 'Origin': args.base}
        csrf = next((c.value for c in jar if c.name == 'mhq_gm_csrf'), '')
        if csrf:
            headers['X-CSRF-Token'] = csrf
        raw = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(args.base + '/api/v1' + path, raw, headers)
        with opener.open(req, timeout=30) as response:
            result = json.load(response)
            if result.get('error'):
                raise RuntimeError(result['error'].get('code', 'API error'))
            return result['data']

    api('/auth/login', {'username': env.get('GM_ADMIN_USERNAME', 'admin'),
                        'password': env['GM_ADMIN_PASSWORD']})
    try:
        endpoint = f'/players/{args.player}'
        data = {'capturedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'evidenceType': 'server-state-only', 'health': api('/health'),
                'detail': api(endpoint)}
        for resource in ('inventory', 'equipment', 'skills', 'tasks', 'pets',
                         'starsouls', 'activity', 'mails'):
            data[resource] = api(endpoint + '/' + resource)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise RuntimeError('Refusing to overwrite a previous evidence snapshot')
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Captured player #{args.player}: {args.output.name}; UI proof remains separate.')
    finally:
        api('/auth/logout', {})


if __name__ == '__main__':
    main()
