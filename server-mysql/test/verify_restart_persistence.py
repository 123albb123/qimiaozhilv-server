"""Seed an isolated online role, observe a forced disconnect, then verify storage."""
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import uuid

from verify_nas_soak import Client


def main():
    assert os.environ.get('MHQ_RESTART_ALLOW_ISOLATED') == '1'
    phase = sys.argv[1]
    snapshot = Path(os.environ['MHQ_RESTART_SNAPSHOT'])
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ''

    def api(path, payload=None):
        req = urllib.request.Request('http://qimiao-test-gm-api:8080/api/v1' + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': uuid.uuid4().hex})
        with opener.open(req, timeout=30) as response:
            result = json.load(response)
        assert not result.get('error'), result
        return result['data']

    assert api('/health')['version'].startswith('isolated-')
    csrf = api('/auth/login', {'username': 'testadmin', 'password': os.environ['GM_ADMIN_PASSWORD']})['csrfToken']
    if phase == 'seed':
        assert not snapshot.exists(), 'never overwrite existing test credentials'
        account, password = 'Restart' + uuid.uuid4().hex[:10], uuid.uuid4().hex[:16]
        client = Client()
        player_id = client.enter(account, password, create=True, index=77)
        path = '/players/' + str(player_id)
        result = api(path + '/items/grant', {'payload': {'items': [{'itemId': 110305, 'count': 2}, {'itemId': 120227, 'count': 1}]}})
        assert result['status'] == 'completed', result
        result = api(path + '/currency-adjust', {'payload': {'currency': 'coin', 'delta': '1'}})
        assert result['status'] == 'completed', result
        expected = {'account': account, 'password': password, 'playerId': player_id,
                    'bag': client.bag(), 'coin': api(path)['coin'], 'config': api('/configs/Gameplay')['content']}
        snapshot.write_text(json.dumps(expected), encoding='utf-8')
        snapshot.chmod(0o600)
        print('SEEDED_ONLINE_ROLE', player_id, flush=True)
        try:
            for _ in range(60):
                client.rpc(20333)
                time.sleep(1)
        except (ConnectionError, OSError, TimeoutError):
            print('FORCED_DISCONNECT_OBSERVED', flush=True)
        else:
            raise AssertionError('expected the isolated helper to terminate the game')
        finally:
            client.close()
    elif phase == 'check':
        expected = json.loads(snapshot.read_text(encoding='utf-8'))
        client = Client()
        try:
            player_id = client.enter(expected['account'], expected['password'])
            assert player_id == expected['playerId']
            assert [list(row) for row in client.bag()] == expected['bag'], 'inventory changed across SIGKILL/restart'
            assert api('/players/' + str(player_id))['coin'] == expected['coin'], 'currency changed across restart'
            assert api('/configs/Gameplay')['content'] == expected['config'], 'restart replaced the published MySQL config'
            print('PASS: same role, granted goods/equipment and exact currency survived SIGKILL and API restart')
        finally:
            client.close()
    else:
        raise ValueError('phase must be seed or check')


if __name__ == '__main__':
    main()
