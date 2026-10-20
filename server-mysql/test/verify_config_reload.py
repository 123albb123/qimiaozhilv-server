"""Real isolated GM -> MySQL -> Redis -> running-game publish/rollback check."""
import http.cookiejar
import json
import os
import re
import urllib.request


def main():
    assert os.environ.get('MHQ_CONFIG_ALLOW_ISOLATED') == '1'
    base = os.environ.get('MHQ_CONFIG_GM_URL', 'http://qimiao-test-gm-api:8080')
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    csrf = ''

    def api(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(base + '/api/v1' + path, data=data,
                                     headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
        with opener.open(req, timeout=30) as response:
            result = json.load(response)
        assert not result.get('error'), result
        return result['data']

    assert api('/health')['version'].startswith('isolated-'), 'production config writes forbidden'
    csrf = api('/auth/login', {'username': 'testadmin', 'password': os.environ['GM_ADMIN_PASSWORD']})['csrfToken']
    before = api('/configs/Gameplay')
    text = before['contentYaml']
    matched = re.search(r'(questions_per_round:\s*)(\d+)', text)
    assert matched
    alternate = '11' if matched[2] != '11' else '10'
    changed = text[:matched.start(2)] + alternate + text[matched.end(2):]
    assert api('/configs/Gameplay/validate', {'contentYaml': changed})['valid']
    published = None
    rollback_revision = None
    try:
        published = api('/configs/Gameplay/publish', {'contentYaml': changed, 'note': 'isolated live reload regression'})
        history = api('/configs/Gameplay/revisions')['items']
        rollback_revision = str(max(int(row['revision']) for row in history if int(row['revision']) < int(published['revision'])))
        assert published['reloadStatus'] == 'applied', published
        state = api('/configs/Gameplay/reload')
        assert state['status'] == 'applied' and state['revision'] == published['revision'], state
        assert api('/configs/Gameplay')['content'] != before['content']
        assert rollback_revision, history
        print('LIVE_PUBLISH_APPLIED', published['revision'])
    finally:
        # Restore the pre-test value even when a runtime acknowledgement fails.
        if rollback_revision is not None:
            restored = api('/configs/Gameplay/revisions/' + rollback_revision + '/rollback', {})
            assert restored['reloadStatus'] == 'applied', restored
            assert api('/configs/Gameplay')['content'] == before['content']
            print('LIVE_ROLLBACK_APPLIED', restored['revision'])
    same = api('/configs/Gameplay/publish', {'contentYaml': text, 'note': 'same-value retry'})
    assert same['revision'] == restored['revision'], same
    print('SAME_VALUE_RETRY_NO_NEW_REVISION', same['revision'])
    api('/auth/logout', {})
    print('PASS: running game acknowledged real publish and rollback; original config restored')


if __name__ == '__main__':
    main()
