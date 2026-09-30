"""Canvas transport shared by every grading mode. Credentials stay at the configured origin."""
from urllib.parse import urlparse, urljoin
import requests


class CanvasError(Exception):
    pass


class CanvasTransport:
    def __init__(self, base, token, session=None):
        p = urlparse(base)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
            raise CanvasError('CANVAS_BASE_URL must be an HTTPS site origin.')
        if not token:
            raise CanvasError('Create the local .env file with CANVAS_BASE_URL and CANVAS_TOKEN first.')
        self.base, self.token = base.rstrip('/'), token
        self.session = session or requests.Session()

    def get(self, path, params=None):
        url = urljoin(self.base, path)
        p, base = urlparse(url), urlparse(self.base)
        if (p.scheme, p.netloc) != (base.scheme, base.netloc) or not p.path.startswith('/api/v1/'):
            raise CanvasError('Canvas returned an unsafe pagination URL; retrieval stopped.')
        try:
            response = self.session.get(url, params=params, headers={'Authorization': f'Bearer {self.token}'}, timeout=(10, 40), allow_redirects=False)
            if response.status_code != 200:
                messages = {401: 'Canvas authentication failed. Check your local token.', 403: 'Canvas denied access. Check course permissions and quiz settings.', 404: 'Canvas could not find this resource.', 429: 'Canvas rate limit reached. Wait a moment, then reload.'}
                raise CanvasError(messages.get(response.status_code, f'Canvas request failed (HTTP {response.status_code}). Try again later.'))
            return response.json(), response.links.get('next', {}).get('url')
        except (requests.RequestException, ValueError):
            raise CanvasError('Canvas connection timed out, failed, or returned invalid data. Check the site and try again.') from None

    def pages(self, path, key=None, params=None):
        result, seen = [], set()
        while path:
            if path in seen:
                raise CanvasError('Canvas pagination repeated a page; retrieval stopped.')
            seen.add(path)
            data, next_path = self.get(path, params)
            rows = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise CanvasError('Canvas returned an unexpected list format.')
            result.extend(rows)
            path, params = next_path, None
        return result

    def put(self, path, payload):
        """One write, never retried or redirected. Any failure means the outcome is uncertain."""
        try:
            response = self.session.put(self.base + path, json=payload, headers={'Authorization': f'Bearer {self.token}'}, timeout=(10, 40), allow_redirects=False)
            if response.status_code != 200:
                raise CanvasError(f'Canvas upload returned HTTP {response.status_code}. Verify the result in Canvas before retrying.')
        except requests.RequestException:
            raise CanvasError('Upload connection failed. Its outcome is uncertain; verify in Canvas before retrying.') from None
