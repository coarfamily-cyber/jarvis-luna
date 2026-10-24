"""Fixed four-request connection check; no product API or persistent token storage.

Receipt proves shop/scopes, not credential provenance or live writer authority.
Transport deliberately ignores proxy settings on the hosted GitHub runner.
"""
import http.client
import ipaddress
import json
import math
import os
import re
import signal
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlencode

HOST = 'rb3zh1-i1.myshopify.com'
PUBLIC_ALIAS = 'coarfamily.myshopify.com'
CANONICAL_DOMAIN = 'rb3zh1-i1.myshopify.com'
SHOP_ID = 82748997889
API_VERSION = '2026-10'
APP_ID = 'gid://shopify/App/433866375169'
INSTALLATION_ID = 'gid://shopify/AppInstallation/736198263041'
IDENTITY_QUERY = 'query JarvisReadonlyIdentity { currentAppInstallation { id app { id } } }'
IDENTITY_BODY = json.dumps({'query': IDENTITY_QUERY}, separators=(',', ':')).encode()
LIMIT = 65536
REQUIRED = frozenset({'write_products', 'read_inventory', 'read_publications'})
OPERATIONS = {
    'token': ('POST', '/admin/oauth/access_token'),
    'shop': ('GET', '/admin/api/2026-10/shop.json?fields=id,myshopify_domain'),
    'identity': ('POST', '/admin/api/2026-10/graphql.json'),
    'scopes': ('GET', '/admin/oauth/access_scopes.json'),
}

SAFE_CODES = frozenset(('ambiguous_response_framing', 'ambiguous_response_headers', 'app_identity_mismatch', 'app_identity_read_failed', 'client_credentials_missing_or_invalid', 'configuration_invalid', 'dns_empty', 'duplicate_json_key', 'encoded_response', 'http_error', 'http_forbidden', 'http_rate_limited', 'http_server_error', 'http_unauthorized', 'internal_error_redacted', 'invalid_json', 'invalid_response_shape', 'mixed_credential_route_forbidden', 'nonpublic_address', 'preflight_failed_redacted', 'readonly_preflight_failed_redacted', 'redirect_refused', 'request_order_or_budget_invalid', 'request_shape_invalid', 'required_scopes_missing_or_duplicate', 'response_size_invalid', 'response_type_invalid', 'scope_response_invalid', 'shop_identity_mismatch', 'store_configuration_mismatch', 'token_expiry_invalid', 'token_response_invalid', 'total_deadline_exceeded', 'transport_cleanup_failed', 'transport_failed_no_retry', 'unsupported_transfer_encoding'))
SAFE_STAGES = frozenset({'configuration', 'token_exchange', 'shop_identity', 'app_identity', 'granted_scopes', 'unknown'})
STAGES = {'token': 'token_exchange', 'shop': 'shop_identity', 'identity': 'app_identity', 'scopes': 'granted_scopes'}


class PreflightError(Exception):
    """Only closed-set static metadata; never retain a caller exception string."""
    def __init__(self, code, stage='configuration'):
        self.code = code if type(code) is str and code in SAFE_CODES else 'internal_error_redacted'
        self.stage = stage if type(stage) is str and stage in SAFE_STAGES else 'unknown'
        super().__init__(self.code)



def require(condition, code):
    if not condition:
        raise PreflightError(code)


def decode(raw):
    def finite_float(text):
        value = float(text)
        require(math.isfinite(value), 'invalid_json')
        return value
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    require(isinstance(raw, bytes) and len(raw) <= LIMIT, 'response_size_invalid')
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                           parse_float=finite_float)
    except Exception:
        raise PreflightError('invalid_json') from None
    require(isinstance(value, dict), 'invalid_response_shape')
    return value


class FixedTransport:
    """One ordered attempt, TLS with public pinned IP, no redirects or retries."""
    _operations = OPERATIONS
    _bodies = {'identity': IDENTITY_BODY}
    _stages = STAGES

    def __init__(self):
        self.next_operation = 0

    def __call__(self, operation, *, body=None, token=None):
        order = tuple(self._operations)
        require(self.next_operation < len(order) and operation == order[self.next_operation],
                'request_order_or_budget_invalid')
        self.next_operation += 1  # An uncertain request consumes its attempt.
        method, path = self._operations[operation]
        require((operation == 'token' and isinstance(body, bytes) and token is None) or
                (operation != 'token' and body is None and isinstance(token, str)),
                'request_shape_invalid')
        connection = None
        sock = None
        try:
            addresses = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
            require(bool(addresses), 'dns_empty')
            require(all(ipaddress.ip_address(r[4][0]).is_global and
                        not ipaddress.ip_address(r[4][0]).is_multicast and
                        not ipaddress.ip_address(r[4][0]).is_reserved for r in addresses),
                    'nonpublic_address')
            family, kind, protocol, _, address = addresses[0]
            sock = socket.socket(family, kind, protocol)
            sock.settimeout(15)
            sock.connect(address)
            connection = http.client.HTTPSConnection(HOST, timeout=15)
            connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)
            headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity',
                       'User-Agent': 'JarvisReadOnlyPreflight/1'}
            if operation == 'token':
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
            else:
                headers['X-Shopify-Access-Token'] = token
            if operation in self._bodies:
                body = self._bodies[operation]
                headers['Content-Type'] = 'application/json'
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            pairs = response.getheaders()
            names = [key.lower() for key, _ in pairs]
            require(all(names.count(key) <= 1 for key in
                        ('content-length', 'content-encoding', 'content-type', 'transfer-encoding')),
                    'ambiguous_response_headers')
            h = {key.lower(): value for key, value in pairs}
            status = response.status
            if status != 200:
                code = {401: 'http_unauthorized', 403: 'http_forbidden',
                        429: 'http_rate_limited'}.get(status, 'http_error')
                if type(status) is int and 300 <= status < 400:
                    code = 'redirect_refused'
                elif type(status) is int and 500 <= status < 600:
                    code = 'http_server_error'
                raise PreflightError(code)
            require(h.get('content-encoding', 'identity') == 'identity', 'encoded_response')
            require(h.get('content-type', '').split(';')[0].strip() == 'application/json',
                    'response_type_invalid')
            length = h.get('content-length')
            require(length is None or (re.fullmatch(r'[0-9]{1,6}', length) and int(length) <= LIMIT), 'response_size_invalid')
            require(h.get('transfer-encoding') in (None, 'chunked'), 'unsupported_transfer_encoding')
            require(not (length and h.get('transfer-encoding')), 'ambiguous_response_framing')
            raw = response.read(LIMIT + 1)
            require(len(raw) <= LIMIT and (length is None or len(raw) == int(length)),
                    'response_size_invalid')
            return raw
        except PreflightError as error:
            raise PreflightError(getattr(error, 'code', None), self._stages[operation]) from None
        except Exception:
            raise PreflightError('transport_failed_no_retry', self._stages[operation]) from None
        finally:
            try:
                if connection is not None:
                    connection.close()
                elif sock is not None:
                    sock.close()
            except Exception:
                raise PreflightError('transport_cleanup_failed') from None


def _verified_session(environ, *, transport=None):
    require(environ.get('SHOPIFY_STORE') == HOST, 'store_configuration_mismatch')
    require(not environ.get('SHOPIFY_ADMIN_TOKEN'), 'mixed_credential_route_forbidden')
    client_id, secret = environ.get('SHOPIFY_CLIENT_ID'), environ.get('SHOPIFY_CLIENT_SECRET')
    require(all(isinstance(v, str) and 1 <= len(v) <= 4096 and
                v.isascii() and not any(c.isspace() or ord(c) < 32 for c in v)
                for v in (client_id, secret)), 'client_credentials_missing_or_invalid')
    transport = transport or FixedTransport()
    stage = 'token_exchange'
    try:
        auth = decode(transport('token', body=urlencode({
            'grant_type': 'client_credentials', 'client_id': client_id,
            'client_secret': secret}).encode()))
        token = auth.get('access_token')
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_\-.]{1,4096}', token),
                'token_response_invalid')
        expiry = auth.get('expires_in')
        require(type(expiry) is int and 0 < expiry <= 86400, 'token_expiry_invalid')
        stage = 'shop_identity'
        shop = decode(transport('shop', token=token)).get('shop')
        require(isinstance(shop, dict) and type(shop.get('id')) is int and
                shop['id'] == SHOP_ID and shop.get('myshopify_domain') == CANONICAL_DOMAIN,
                'shop_identity_mismatch')
        stage = 'app_identity'
        identity = decode(transport('identity', token=token))
        require(not identity.get('errors'), 'app_identity_read_failed')
        data = identity.get('data')
        installation = data.get('currentAppInstallation') if isinstance(data, dict) else None
        require(isinstance(installation, dict) and installation.get('id') == INSTALLATION_ID and
                isinstance(installation.get('app'), dict) and installation['app'].get('id') == APP_ID,
                'app_identity_mismatch')
        stage = 'granted_scopes'
        rows = decode(transport('scopes', token=token)).get('access_scopes')
        require(isinstance(rows, list) and len(rows) <= 256 and all(
            isinstance(r, dict) and set(r) == {'handle'} and isinstance(r['handle'], str)
            and re.fullmatch(r'(read|write)_[a-z_]+', r['handle']) for r in rows),
            'scope_response_invalid')
        scopes = {r['handle'] for r in rows}
        require(len(scopes) == len(rows) and REQUIRED <= scopes, 'required_scopes_missing_or_duplicate')
        receipt = {'schema_version': 1, 'status': 'readonly_connection_verified',
                'observed_at': datetime.now(timezone.utc).isoformat(), 'shop_id': SHOP_ID,
                'transport_host': HOST, 'canonical_domain': CANONICAL_DOMAIN, 'api_version': API_VERSION,
                'scope_names': sorted(scopes), 'excess_scope_names': sorted(scopes - REQUIRED),
                'token_expiry_seconds': expiry, 'product_writes': 0,
                'live_writer_authorized': False, 'app_identity_independently_verified': True,
                'app_id': APP_ID, 'installation_id': INSTALLATION_ID}
        return receipt, token
    except PreflightError as error:
        raise PreflightError(getattr(error, 'code', None), stage) from None
    except Exception:
        raise PreflightError('preflight_failed_redacted', stage) from None


def run(environ, *, transport=None):
    # Public preflight output remains credential-free and exactly the same schema.
    receipt, _ = _verified_session(environ, transport=transport)
    return receipt


def main():
    def deadline(*_):
        raise PreflightError('total_deadline_exceeded')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(100)
    try:
        receipt = run(os.environ)
    except Exception as error:
        # Reconstruct through the closed sets even if an unexpected caller altered attributes.
        safe = PreflightError(getattr(error, 'code', None), getattr(error, 'stage', None)) if type(error) is PreflightError else PreflightError('internal_error_redacted', 'unknown')
        print(json.dumps({'status': 'blocked', 'error': safe.code, 'stage': safe.stage,
                          'live_writer_authorized': False}))
        return 1
    finally:
        signal.alarm(0)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
