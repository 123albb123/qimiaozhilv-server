"""Keep long HTTP-driven protocol tests alive like the native Unity client."""
import struct
import threading


class HeartbeatSocket:
    def __init__(self, sock):
        self._socket = sock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._error = None
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def __getattr__(self, name):
        return getattr(self._socket, name)

    def sendall(self, data, *args):
        with self._lock:
            if self._error is not None:
                raise ConnectionError('protocol heartbeat failed') from self._error
            return self._socket.sendall(data, *args)

    def _heartbeat(self):
        while not self._stop.wait(2):
            try:
                # Ping has an empty protobuf body and RpcId zero. Existing
                # readers retain the 20334 reply among unsolicited frames.
                self.sendall(struct.pack('<HH', 2, 20333))
            except OSError as error:
                self._error = error
                return

    def close(self):
        self._stop.set()
        with self._lock:
            self._socket.close()
        self._thread.join(timeout=2)
