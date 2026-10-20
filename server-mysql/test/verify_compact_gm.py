"""Verify the combined GM listener against an explicitly isolated game."""
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.request
import uuid

from verify_gm_items_mail import Game, field, fields, vf


def main():
    assert os.environ.get('MHQ_COMPACT_ALLOW_ISOLATED') == '1', 'explicit isolated opt-in required'
    assert os.environ.get('MHQ_TEST_HOST', '127.0.0.1') in ('127.0.0.1', 'localhost')
    base = os.environ['MHQ_COMPACT_GM_URL'].rstrip('/')
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def request(path, data=None, expected=200, extra=None, key=None):
        headers = {'Origin': base, 'Content-Type': 'application/json'}
        csrf = next((c.value for c in jar if c.name == 'mhq_gm_csrf'), '')
        if csrf:
            headers['X-CSRF-Token'] = csrf
        if key:
            headers['Idempotency-Key'] = key
        headers.update(extra or {})
        raw = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        req = urllib.request.Request(base + path, data=raw, headers=headers)
        try:
            response = opener.open(req, timeout=25)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            assert response.status == expected, (path, response.status, expected)
            return body, response.headers

    def api(path, data=None, expected=200, extra=None, key=None):
        body, _ = request('/api/v1' + path, data, expected, extra, key)
        result = json.loads(body)
        if expected == 200:
            assert not result.get('error'), (path, result.get('error', {}).get('code'))
        return result.get('data') if expected == 200 else result

    health = api('/health')
    assert health.get('version', '').startswith('isolated-'), 'refusing production write tests'
    index, headers = request('/')
    assert b'<!doctype html>' in index.lower() and headers.get('Cache-Control') == 'no-cache'
    routes = ['/login', '/players', '/players/1', '/accounts', '/admins', '/password',
              '/batch', '/broadcast', '/operations', '/configs', '/sub-gms', '/audit']
    for route in routes:
        body, _ = request(route)
        assert body == index, ('SPA route did not retain the same application', route)
    assets = re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', index)
    assert assets, 'production JS/CSS missing'
    for asset in assets:
        body, response_headers = request(asset.decode())
        assert body and b'<!doctype html>' not in body[:100].lower()
        assert 'immutable' in response_headers.get('Cache-Control', '')
    request('/assets/absent.js', expected=404)
    request('/.env', expected=404)
    api('/players', expected=401)
    api('/auth/login', {'username': os.environ.get('GM_ADMIN_USERNAME', 'testadmin'),
                        'password': os.environ['GM_ADMIN_PASSWORD']})
    assert api('/auth/me')['username'] == os.environ.get('GM_ADMIN_USERNAME', 'testadmin')
    for route in ['/dashboard', '/accounts', '/players', '/admins', '/items', '/skills', '/configs', '/audit', '/commands', '/sub-gms']:
        api(route)
    game = Game()
    try:
        player_id = game.login('cmp' + uuid.uuid4().hex[:12], uuid.uuid4().hex[:16], create=True)
        endpoint = f'/players/{player_id}'
        before = game.bag()
        grant = {'payload': {'items': [{'itemId': 110305, 'count': 2}]}}
        api(endpoint + '/items/grant', grant, expected=403,
            extra={'Origin': 'http://untrusted.invalid', 'X-Forwarded-Host': 'untrusted.invalid'})
        assert game.bag() == before, 'rejected cross-origin request modified inventory'
        key = uuid.uuid4().hex
        assert api(endpoint + '/items/grant', grant, key=key)['status'] == 'completed'
        api(endpoint + '/items/grant', grant, key=key)
        assert game.bag()[110305] == before[110305] + 2, 'grant or idempotency changed'
        mail = {'payload': {'title': '容器合并联调', 'content': '原生邮件附件保持正常',
                            'items': [{'itemId': 110306, 'count': 3}]}}
        result = api(endpoint + '/mail', mail, key=uuid.uuid4().hex)
        assert result['status'] == 'completed'
        mail_id = int(result['data']['mailId'])
        page = [row for tag, row in fields(game.rpc(20281, vf(1, 1))) if tag == 1]
        selected = [row for row in page if field(row, 8) == mail_id]
        assert len(selected) == 1 and field(selected[0], 2).decode() == mail['payload']['title']
        potion_before = game.bag()[110306]
        game.rpc(20283, vf(1, mail_id) + vf(2, 1))
        assert game.bag()[110306] == potion_before + 3
        api('/auth/logout', {})
        api('/auth/me', expected=401)
    finally:
        game.sock.close()
    print('PASS compact GM: 12 SPA routes, production assets, real login/read/logout, '
          'same-origin CSRF rejection, idempotent online grant, native Chinese mail and attachment claim')


if __name__ == '__main__':
    main()
