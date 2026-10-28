"""HTTP 层：起一个真实服务器（随机端口），走一遍关键接口。"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from workhub import server


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read()


def post(url, body, headers=None):
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 真实 target_state 要起子进程探测各家版本，测试里换成桩，只验路由与结构
        cls._real_target_state = server.target_state
        server.target_state = lambda tid: {
            "id": tid, "name": tid, "headline": "stub", "kind": "test",
            "running": True, "pids": [], "detail": "", "config": "", "cost": "",
            "actions": [], "version": "0",
        }
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        server.target_state = cls._real_target_state
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_healthz(self):
        code, body = get(self.base + "/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(body, b"ok")

    def test_index_html_served(self):
        code, body = get(self.base + "/")
        self.assertEqual(code, 200)
        self.assertIn(b"WorkHub", body)

    def test_state_has_five_targets(self):
        code, body = get(self.base + "/api/state")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual([t["id"] for t in data["targets"]],
                         ["codex", "workbuddy", "dsh", "kimi", "muse"])
        self.assertEqual(data["hub"]["name"], "WorkHub")

    def test_templates_endpoint(self):
        code, body = get(self.base + "/api/templates")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertGreaterEqual(len(data["templates"]), 5)

    def test_artifact_path_traversal_is_forbidden(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            get(self.base + "/artifact?path=../config.json")
        self.assertEqual(ctx.exception.code, 403)

    def test_unknown_route_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            get(self.base + "/api/nope")
        self.assertEqual(ctx.exception.code, 404)


class TestChainRoute(unittest.TestCase):
    """/api/chain 的参数校验（真的派发要起子进程，这里只测拦得住的入参）。"""

    @classmethod
    def setUpClass(cls):
        cls._real_target_state = server.target_state
        server.target_state = lambda tid: {
            "id": tid, "name": tid, "headline": "stub", "kind": "test",
            "running": True, "pids": [], "detail": "", "config": "", "cost": "",
            "actions": [], "version": "0",
        }
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        server.target_state = cls._real_target_state
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_single_step_is_rejected(self):
        code, body = post(self.base + "/api/chain", {"steps": [{"target": "codex", "prompt": "x"}]})
        self.assertEqual(code, 400)
        self.assertIn("2–", body["message"])

    def test_handoff_target_is_rejected(self):
        code, body = post(self.base + "/api/chain", {"steps": [
            {"target": "workbuddy", "prompt": "写个方案"},
            {"target": "codex", "prompt": "整理"}]})
        self.assertEqual(code, 400)
        self.assertIn("人工接力", body["message"])

    def test_empty_prompt_is_rejected(self):
        code, body = post(self.base + "/api/chain", {"steps": [
            {"target": "codex", "prompt": " "},
            {"target": "dsh", "prompt": "整理"}]})
        self.assertEqual(code, 400)
        self.assertIn("第 1 步", body["message"])


class TestTokenGuard(unittest.TestCase):
    def setUp(self):
        self._old = server.TOKEN
        server.TOKEN = "s3cret"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        server.TOKEN = self._old
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_api_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            get(self.base + "/api/state")
        self.assertEqual(ctx.exception.code, 401)

    def test_api_accepts_header_or_query(self):
        code, _ = get(self.base + "/api/state", {"X-WorkHub-Token": "s3cret"})
        self.assertEqual(code, 200)
        code, _ = get(self.base + "/api/state?token=s3cret")
        self.assertEqual(code, 200)

    def test_index_still_public(self):
        code, _ = get(self.base + "/")
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
