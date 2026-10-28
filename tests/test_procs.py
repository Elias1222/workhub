"""进程层：端口探测（跨平台，不依赖任何外部程序）。"""
import socket
import unittest

from workhub import procs


class TestProcs(unittest.TestCase):
    def test_port_open_on_listening_socket(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            self.assertTrue(procs.port_open(port, timeout=1.0))
        finally:
            sock.close()

    def test_closed_port_reports_false(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        self.assertFalse(procs.port_open(port, timeout=0.3))

    def test_list_pids_never_raises(self):
        self.assertIsInstance(procs.list_pids("definitely-not-a-real-process-xyz"), list)


if __name__ == "__main__":
    unittest.main()
