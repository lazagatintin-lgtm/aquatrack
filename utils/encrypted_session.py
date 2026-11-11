import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask.json.tag import TaggedJSONSerializer
from flask.sessions import SecureCookieSession, SessionInterface


class EncryptedCookieSessionInterface(SessionInterface):
    serializer = TaggedJSONSerializer()

    def __init__(self, secret_key):
        key = base64.urlsafe_b64encode(
            hashlib.sha256(secret_key.encode("utf-8")).digest()
        )
        self.fernet = Fernet(key)

    def open_session(self, app, request):
        cookie_name = self.get_cookie_name(app)
        token = request.cookies.get(cookie_name)

        if not token:
            return SecureCookieSession()

        try:
            payload = self.fernet.decrypt(
                token.encode("ascii"),
                ttl=int(app.permanent_session_lifetime.total_seconds())
            )
            data = self.serializer.loads(payload.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, ValueError, TypeError):
            session = SecureCookieSession()
            session.modified = True
            return session

        if not isinstance(data, dict):
            session = SecureCookieSession()
            session.modified = True
            return session

        return SecureCookieSession(data)

    def save_session(self, app, session, response):
        cookie_name = self.get_cookie_name(app)
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        if session.accessed:
            response.vary.add("Cookie")

        if not session:
            if session.modified:
                response.delete_cookie(
                    cookie_name,
                    domain=domain,
                    path=path,
                    secure=self.get_cookie_secure(app),
                    httponly=self.get_cookie_httponly(app),
                    samesite=self.get_cookie_samesite(app)
                )
                response.vary.add("Cookie")
            return

        if not session.modified:
            return

        serialized = self.serializer.dumps(dict(session)).encode("utf-8")
        encrypted = self.fernet.encrypt(serialized).decode("ascii")

        response.set_cookie(
            cookie_name,
            encrypted,
            expires=self.get_expiration_time(app, session),
            httponly=self.get_cookie_httponly(app),
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
            domain=domain,
            path=path
        )
        response.vary.add("Cookie")