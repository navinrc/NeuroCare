"""Run the account-linking OAuth flow against Cognito without a browser (phase 6 verification).

Does what Alexa+ does: authorization code + PKCE S256 through the hosted UI sign-in page, code
exchange with the client secret, then a refresh-token grant. Prints the access token to stdout
(nothing else), so it can feed ``scripts/latency.py``; checks go to stderr.

    COGNITO_DOMAIN=<prefix>.auth.us-east-1.amazoncognito.com CLIENT_ID=... CLIENT_SECRET=... \\
    DEMO_EMAIL=... DEMO_PASSWORD=... uv run python scripts/oauth_token.py

The redirect URI is the MCP Inspector callback (registered on the client); nothing listens there,
the code is read from the redirect's ``Location`` header.
"""

import base64
import hashlib
import html
import http.cookiejar
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

REDIRECT = "http://localhost:6274/oauth/callback"
SCOPE = "openid email neurocare/tools"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def say(message: str) -> None:
    print(message, file=sys.stderr)


def main() -> None:
    domain, client_id, secret = os.environ["COGNITO_DOMAIN"], os.environ["CLIENT_ID"], os.environ["CLIENT_SECRET"]
    email, password = os.environ["DEMO_EMAIL"], os.environ["DEMO_PASSWORD"]
    base = f"https://{domain}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect())

    def fetch(url: str, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict, str]:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        request = urllib.request.Request(url, data=body, headers=headers or {})
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read().decode()
        except urllib.error.HTTPError as error:  # 3xx land here because redirects are not followed
            return error.code, dict(error.headers), error.read().decode(errors="replace")

    def authorize(verifier: str) -> str:
        """Authorize with PKCE S256, signing in on the hosted UI if there is no session yet; returns the code."""
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        status, headers, _ = fetch(f"{base}/oauth2/authorize?{query}")
        location = headers.get("Location", "")
        if "code=" not in location:
            login_url = urllib.parse.urljoin(base, location)
            status, _, page = fetch(login_url)
            csrf = re.search(r'name="_csrf"\s+value="([^"]+)"', page)
            if status != 200 or csrf is None:
                raise SystemExit(f"sign-in page: HTTP {status}, no _csrf field")
            form = {"_csrf": html.unescape(csrf.group(1)), "username": email, "password": password}
            status, headers, _ = fetch(login_url, {**form, "signInSubmitButton": "Sign in"})
            location = headers.get("Location", "")
            say(f"sign-in → {status}")
        params = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        if "code" not in params:
            raise SystemExit("no authorization code in the redirect (wrong password?)")
        if params.get("state") != [state]:
            raise SystemExit("state mismatch")
        return params["code"][0]

    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    token_headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}

    def token(grant: dict) -> tuple[int, dict]:
        status, _, body = fetch(f"{base}/oauth2/token", grant, token_headers)
        return status, json.loads(body)

    def exchange(code: str, verifier: str) -> tuple[int, dict]:
        grant = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier}
        return token(grant)

    verifier = secrets.token_urlsafe(48)
    status, bad = exchange(authorize(verifier), "wrong-" + verifier)
    say(f"token with a wrong PKCE verifier → {status} {bad.get('error')}")
    if status == 200:
        raise SystemExit("PKCE NOT enforced: a wrong code_verifier was accepted")

    verifier = secrets.token_urlsafe(48)
    status, tokens = exchange(authorize(verifier), verifier)
    if status != 200:
        raise SystemExit(f"token exchange: HTTP {status} {tokens}")
    claims = json.loads(base64.urlsafe_b64decode(tokens["access_token"].split(".")[1] + "=="))
    say(f"token → 200; refresh_token issued: {'refresh_token' in tokens}; scope: {claims.get('scope')}")
    status, refreshed = token({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    say(f"refresh → {status}; new access token: {'access_token' in refreshed}")
    print(refreshed.get("access_token") or tokens["access_token"])


if __name__ == "__main__":
    main()
