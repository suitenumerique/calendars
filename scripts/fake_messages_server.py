"""Fake Messages API server for local development.

Simulates the provisioning and submit endpoints so we can test
mailbox integration without a real Messages instance.

Test users (from Keycloak realm):
  user1@example.local / user1  → admin on contact@, sender on support@,
                                  admin on own email (personal mailbox)
  user2@example.local / user2  → sender on contact@, viewer on support@
  user3@example.local / user3  → viewer on contact@

Usage:
    python scripts/fake_messages_server.py
    # or: make fake-messages
    # Listens on port 8940
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8940

# Fake mailboxes with their users
MAILBOXES = {
    "contact@example.local": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "email": "contact@example.local",
        "name": "Contact Team",
        "maildomain_custom_attributes": {"siret": "example.local"},
        "users": [
            {"email": "user1@example.local", "role": "admin"},
            {"email": "user2@example.local", "role": "sender"},
            {"email": "user3@example.local", "role": "viewer"},
        ],
    },
    "support@example.local": {
        "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "email": "support@example.local",
        "name": "Support",
        "maildomain_custom_attributes": {"siret": "example.local"},
        "users": [
            {"email": "user1@example.local", "role": "sender"},
            {"email": "user2@example.local", "role": "viewer"},
        ],
    },
    "user1@example.local": {
        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "email": "user1@example.local",
        "name": "User One Personal",
        "maildomain_custom_attributes": {"siret": "example.local"},
        "users": [
            {"email": "user1@example.local", "role": "admin"},
        ],
    },
}

# Build per-user index: user_email → mailboxes with their role
USER_MAILBOXES = {}
for mb_email, mb_data in MAILBOXES.items():
    for user in mb_data["users"]:
        entry = {**mb_data, "role": user["role"]}
        USER_MAILBOXES.setdefault(user["email"], []).append(entry)


class FakeMessagesHandler(BaseHTTPRequestHandler):
    def _check_auth(self):
        """Reject requests missing the required X-API-Key / X-Channel-Id."""
        if not self.headers.get("X-API-Key"):
            self._send(401, {"detail": "X-API-Key header required"})
            return False
        if not self.headers.get("X-Channel-Id"):
            self._send(401, {"detail": "X-Channel-Id header required"})
            return False
        return True

    def do_GET(self):
        path = self.path.split("?")[0]
        params = {}
        if "?" in self.path:
            from urllib.parse import parse_qs, urlparse
            params = parse_qs(urlparse(self.path).query)

        if path == "/api/v1.0/provisioning/mailboxes/":
            if not self._check_auth():
                return None
            return self._handle_mailboxes(params)

        self._send(404, {"error": "Not found"})
        return None

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/v1.0/submit/":
            if not self._check_auth():
                return None
            return self._handle_submit()

        self._send(404, {"error": "Not found"})
        return None

    def _handle_mailboxes(self, params):
        user_email = params.get("user_email", [None])[0]
        email = params.get("email", [None])[0]

        if user_email:
            results = USER_MAILBOXES.get(user_email, [])
            self._send(200, {"results": results})
        elif email:
            mb = MAILBOXES.get(email)
            results = [mb] if mb else []
            self._send(200, {"results": results})
        else:
            self._send(400, {"detail": "Provide user_email or email param"})

    def _handle_submit(self):
        mailbox_id = self.headers.get("X-Mail-From", "")
        rcpt_to = self.headers.get("X-Rcpt-To", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        print(f"[submit] From mailbox {mailbox_id} to {rcpt_to} ({len(body)} bytes)")
        self._send(202, {"message_id": "fake-msg-id", "status": "accepted"})

    def _send(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        print(f"[fake-messages] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), FakeMessagesHandler)
    print(f"Fake Messages API running on http://localhost:{PORT}")
    print(f"Mailboxes: {list(MAILBOXES.keys())}")
    print(f"Users: {list(USER_MAILBOXES.keys())}")
    print()
    print("Test accounts (Keycloak):")
    print("  user1@example.local / user1  → admin on contact@, sender on support@,")
    print("                                  admin on own email (personal mailbox)")
    print("  user2@example.local / user2  → sender on contact@, viewer on support@")
    print("  user3@example.local / user3  → viewer on contact@")
    server.serve_forever()
