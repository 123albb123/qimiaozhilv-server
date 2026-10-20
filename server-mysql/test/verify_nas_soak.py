"""Real ten-account TCP soak against an explicitly isolated game deployment."""
import concurrent.futures
import http.cookiejar
import json
import math
import os
from pathlib import Path
import select
import socket
import statistics
import struct
import threading
import time
import urllib.request
import uuid

from verify_gm_items_mail import field, fields, sf, vf

HOST = os.environ.get('MHQ_TEST_HOST', '127.0.0.1')
PORT = int(os.environ.get('MHQ_TEST_PORT', '7756'))
DURATION = int(os.environ.get('MHQ_SOAK_SECONDS', '60'))
LATENCIES = []
METRIC_LOCK = threading.Lock()


class Client:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=10)
        self.buffer = bytearray()
        self.rpc_id = 0
        self.pushes = []

    def close(self):
        self.sock.close()

    def send(self, opcode, body=b''):
        self.sock.sendall(struct.pack('<HH', len(body) + 2, opcode) + body)

    def receive(self, timeout=10):
        deadline = time.monotonic() + timeout
        while True:
            if len(self.buffer) >= 4:
                length, opcode = struct.unpack_from('<HH', self.buffer)
                assert length >= 2, 'invalid frame length'
                if len(self.buffer) >= length + 2:
                    body = bytes(self.buffer[4:length + 2])
                    del self.buffer[:length + 2]
                    return opcode, body
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.sock], [], [], remaining)[0]:
                return None
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('server disconnected')
            self.buffer.extend(chunk)

    def rpc(self, opcode, body=b'', expected=None):
        self.rpc_id += 1
        started = time.monotonic()
        self.send(opcode, body + vf(90, self.rpc_id))
        while time.monotonic() - started < 15:
            response = self.receive(15 - (time.monotonic() - started))
            if response is None:
                break
            op, raw = response
            if op == (opcode + 1 if expected is None else expected) and field(raw, 90) == self.rpc_id:
                assert field(raw, 91, 0) == 0, (opcode, list(fields(raw)))
                with METRIC_LOCK:
                    LATENCIES.append((time.monotonic() - started) * 1000)
                return raw
            self.pushes.append((op, raw))
        raise TimeoutError(f'RPC {opcode} timed out')

    def collect(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            response = self.receive(deadline - time.monotonic())
            if response is None:
                break
            self.pushes.append(response)

    def enter(self, account, password, create=False, index=0):
        if create:
            login = self.rpc(20010, sf(1, account) + sf(2, password))
        else:
            login = self.rpc(20008, sf(1, account) + sf(2, password))
        key, gate = field(login, 2), field(login, 3)
        assert key, 'server did not issue a fresh gate key'
        self.rpc(20014, vf(1, key) + vf(2, gate))
        if create:
            self.rpc(20016, vf(2, 1) + sf(3, f'并发{index}{account[-4:]}'))
        entered = self.rpc(20027)
        player = field(entered, 1)
        assert player, 'enter-game player id missing'
        self.send(20029)
        self.send(20030)
        return player

    def bag(self):
        result = []
        for tag, entry in fields(self.rpc(20258)):
            if tag == 1:
                item = field(entry, 2, b'')
                result.append((field(entry, 1), field(item, 1), field(item, 4)))
        return sorted(result)


def main():
    assert os.environ.get('MHQ_SOAK_ALLOW_ISOLATED') == '1', 'explicit isolated-test opt-in required'
    assert HOST in ('127.0.0.1', 'localhost'), 'run inside the isolated game network namespace'
    assert 10 <= DURATION <= 600
    url = os.environ.get('MHQ_SOAK_GM_URL', 'http://qimiao-test-gm-api:8080')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(path, payload=None):
        raw = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(url + '/api/v1' + path, data=raw, headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=20) as response:
            result = json.load(response)
        assert not result.get('error'), result
        return result['data']

    health = api('/health')
    assert health.get('version', '').startswith('isolated-'), 'refusing to write test accounts to a production GM API'
    api('/auth/login', {'username': 'testadmin', 'password': os.environ['GM_ADMIN_PASSWORD']})
    prefix = 'ns' + uuid.uuid4().hex[:10]
    password = uuid.uuid4().hex[:16]
    ready = threading.Barrier(11)
    release = threading.Event()
    results = [{} for _ in range(10)]
    started = time.monotonic()

    def worker(index):
        account = prefix + str(index)
        client = Client()
        try:
            player = client.enter(account, password, create=True, index=index)
            results[index] = {'account': account, 'playerId': str(player), 'status': 'connected'}
            ready.wait(timeout=40)
            if not release.wait(timeout=30):
                raise TimeoutError('coordinator did not release online clients')
            # Each independent player enters a real main-story battle and
            # issues an attack before the sustained concurrent query phase.
            client.rpc(20031, vf(1, 1000601))
            client.rpc(20048, vf(1, 0))
            client.collect(0.3)
            assert any(op == 20050 for op, _ in client.pushes), 'real battle monster snapshot missing'
            client.rpc(20233, vf(1, 0))
            client.collect(2)
            client.rpc(20171, expected=20171)
            deadline = time.monotonic() + DURATION
            requests = 0
            while time.monotonic() < deadline:
                client.rpc(20333)
                client.bag()
                client.rpc(20239)
                client.rpc(20227)
                requests += 4
                time.sleep(0.8)
            saved_bag = client.bag()
            client.close()
            time.sleep(0.4)
            client = Client()
            assert client.enter(account, password) == player, 'player id changed after reconnect'
            assert client.bag() == saved_bag, 'inventory changed after reconnect'
            results[index].update(status='passed', queryRequests=requests, battleEntered=True, attackRequested=True, reconnectPreserved=True)
        except Exception as error:
            results[index].update(status='failed', error=str(error))
            try:
                ready.abort()
            except Exception:
                pass
            raise
        finally:
            client.close()

    coordinator_error = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(worker, i) for i in range(10)]
        try:
            ready.wait(timeout=45)
            online = api('/players?query=' + prefix + '&online=true&limit=50')['items']
            assert len(online) == 10 and all(player['online'] for player in online), online
            assert {player['id'] for player in online} == {result['playerId'] for result in results}
            print('PASS ten distinct registered accounts are simultaneously online, confirmed by GM API', flush=True)
        except Exception as error:
            coordinator_error = str(error)
        finally:
            release.set()
        for future in futures:
            try:
                future.result()
            except Exception:
                pass

    passed = sum(result.get('status') == 'passed' for result in results)
    duplicate = False
    if passed == 10 and not coordinator_error:
        old, replacement = Client(), Client()
        try:
            old.enter(prefix + '0', password)
            replacement.enter(prefix + '0', password)
            old.collect(2)
            assert any(op == 20328 for op, _ in old.pushes), 'duplicate login did not notify old session'
            duplicate = True
        finally:
            old.close(); replacement.close()
    values = sorted(LATENCIES)
    report = {'type': 'TCP simulation, not Unity-client concurrency', 'accounts': 10, 'simultaneousOnlineConfirmed': coordinator_error is None,
              'soakSeconds': DURATION, 'elapsedSeconds': round(time.monotonic()-started, 3), 'passedAccounts': passed,
              'rpcResponses': len(values), 'rpcLatencyMs': {'mean': round(statistics.mean(values), 3) if values else None,
                  'p95': round(values[max(0, math.ceil(len(values)*0.95)-1)], 3) if values else None, 'max': round(max(values), 3) if values else None},
              'duplicateLoginConfirmed': duplicate, 'coordinatorError': coordinator_error, 'results': results,
              'measurementContext': 'functional isolated test; other build/unit jobs may share NAS resources'}
    output = Path(os.environ.get('MHQ_SOAK_OUTPUT', 'logs/runtime/nas-soak-result.json'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    assert passed == 10 and duplicate and coordinator_error is None, 'ten-account soak failed; see saved report'


if __name__ == '__main__':
    main()
