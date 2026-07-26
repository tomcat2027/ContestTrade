import http.client
import threading
import unittest
import urllib.parse

from web import server as web_server


class WebAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_password = web_server.WEB_PASSWORD
        web_server.WEB_PASSWORD = "test-password"
        web_server._sessions.clear()
        web_server._login_attempts.clear()
        cls.httpd = web_server.http.server.ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        web_server.WEB_PASSWORD = cls.original_password
        web_server._sessions.clear()
        web_server._login_attempts.clear()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        result = response.status, dict(response.getheaders()), payload
        connection.close()
        return result

    def test_login_protects_page_and_api(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/login")

        status, _, payload = self.request("GET", "/api/health")
        self.assertEqual(status, 401)
        self.assertIn(b"authentication required", payload)

        body = urllib.parse.urlencode({"password": "wrong"})
        status, _, payload = self.request(
            "POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded"}
        )
        self.assertEqual(status, 401)
        self.assertIn("密码错误".encode(), payload)

        body = urllib.parse.urlencode({"password": "test-password"})
        status, headers, _ = self.request(
            "POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded"}
        )
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

        status, _, payload = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b"<!DOCTYPE html>", payload)

        status, headers, _ = self.request("POST", "/logout", headers={"Cookie": cookie})
        self.assertEqual(status, 303)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
