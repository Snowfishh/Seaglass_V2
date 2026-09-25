"""Local demo HTTP boundary. Identity and every evidence read are server checked."""

import hmac
import ipaddress
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict
from starlette.middleware.sessions import SessionMiddleware

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditError, AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.providers import configured_provider

WEB = Path(__file__).parent / 'web'
PERSONAS = ('employee', 'finance_lead', 'policy_admin', 'auditor', 'other_tenant', 'disabled')
LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}


class DemoSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str


class ConfiguredSessions:
    """Defer key loading to startup while using Starlette's signed sessions."""

    def __init__(self, app, owner):
        self.app = app
        self.owner = owner
        self.sessions = None

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            if self.sessions is None:
                self.sessions = SessionMiddleware(
                    self.app, secret_key=self.owner.state.settings.session_secret,
                    session_cookie='aspire_demo', same_site='strict', max_age=3600,
                    https_only=False,
                )
            await self.sessions(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def _loopback(request):
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


def _denial(request, reason):
    # No caller-controlled identities or source identifiers enter this local security chain.
    request.app.state.audit.append('local-security', 'anonymous', str(uuid.uuid4()),
                                   'access_denied', {'reason': reason})


def _principal(request):
    if not request.app.state.settings.demo_mode:
        _denial(request, 'identity_unavailable')
        raise HTTPException(401, 'Authentication required')
    identity = request.session.get('user_id')
    if not identity:
        _denial(request, 'authentication_required')
        raise HTTPException(401, 'Authentication required')
    try:
        return request.app.state.auth.principal(identity)
    except AccessDenied:
        _denial(request, 'identity_unavailable')
        raise HTTPException(401, 'Authentication required') from None


def _audit(request, principal, request_id, event_type, metadata=None):
    return request.app.state.audit.append(
        principal['tenant_id'], principal['id'], request_id, event_type, metadata or {},
    )


def _read(request, event, operation):
    principal = _principal(request)
    request_id = str(uuid.uuid4())
    snapshot = (principal, request.app.state.auth.revisions(principal))
    _audit(request, principal, request_id, f'{event}_attempt')
    try:
        value = operation(principal)
    except AccessDenied:
        _audit(request, principal, request_id, 'access_denied', {'status': 'denied'})
        raise HTTPException(404, 'Evidence unavailable') from None
    def verify_snapshot():
        try:
            fresh = request.app.state.auth.principal(principal['id'])
            current = (fresh, request.app.state.auth.revisions(fresh))
        except AccessDenied:
            current = None
        if current != snapshot:
            _audit(request, principal, request_id, f'{event}_aborted', {'status': 'changed'})
            raise HTTPException(409, 'Access or content changed; retry the request')
    verify_snapshot()
    metadata = {'status': 'success'}
    if event == 'source' and isinstance(value, dict):
        metadata = {**metadata, 'version_ids': [value['version_id']], 'chunk_ids': [value['chunk_id']]}
    _audit(request, principal, request_id, f'{event}_completed', metadata)
    verify_snapshot()
    return value


def create_app(settings: Settings | None = None, provider=None):
    @asynccontextmanager
    async def lifespan(application):
        resolved = settings or Settings.load()
        database = Database(resolved.db_path)
        database.initialize()
        audit = AuditWriter(resolved.db_path, resolved.audit_key)
        audit.initialize()
        application.state.settings = resolved
        application.state.db = database
        application.state.auth = AuthService(database)
        application.state.audit = audit
        application.state.queries = QueryService(database, application.state.auth, audit, provider=provider or configured_provider(resolved.provider_mode))
        yield

    app = FastAPI(title='Aspire Internal Brain — local demo', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=WEB / 'templates')

    @app.middleware('http')
    async def security_boundary(request, call_next):
        try:
            if request.url.hostname not in LOOPBACK_HOSTS:
                _denial(request, 'invalid_host')
                response = JSONResponse({'detail': 'Invalid host'}, status_code=400)
            elif request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                token = request.session.get('csrf_token', '')
                supplied = request.headers.get('x-csrf-token', '')
                origin = urlsplit(request.headers.get('origin', ''))
                valid_origin = (origin.scheme == request.url.scheme and origin.netloc == request.url.netloc
                                and not origin.path and not origin.query and not origin.fragment)
                if not token or not hmac.compare_digest(token.encode(), supplied.encode()) or not valid_origin:
                    _denial(request, 'request_verification_failed')
                    response = JSONResponse({'detail': 'Request verification failed'}, status_code=403)
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except AuditError:
            response = JSONResponse({'detail': 'Audit persistence unavailable'}, status_code=503)
        except Exception:
            # Never propagate provider/database exception text into server error logs.
            response = JSONResponse({'detail': 'Service temporarily unavailable'}, status_code=503)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    app.add_middleware(ConfiguredSessions, owner=app)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        _denial(request, 'invalid_request')
        return JSONResponse({'detail': 'Invalid request fields'}, status_code=422)

    @app.exception_handler(AuditError)
    async def audit_error(request, error):
        return JSONResponse({'detail': 'Audit persistence unavailable'}, status_code=503)

    @app.exception_handler(QueryError)
    async def query_error(request, error):
        return JSONResponse({'detail': str(error)}, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({'detail': 'Service temporarily unavailable'}, status_code=503)

    @app.get('/health')
    async def health():
        return {'status': 'ok'}

    @app.get('/sources/{version_id}/{chunk_id}', response_class=HTMLResponse)
    async def citation_page(version_id: str, chunk_id: str, request: Request):
        source_value = _read(request, 'source', lambda p: request.app.state.auth.source(p, version_id, chunk_id))
        return templates.TemplateResponse(request=request, name='source.html', context={'source': source_value})

    @app.get('/api/session')
    async def session(request: Request):
        if 'csrf_token' not in request.session:
            request.session['csrf_token'] = secrets.token_urlsafe(32)
        principal = None
        if request.app.state.settings.demo_mode and request.session.get('user_id'):
            try:
                principal = request.app.state.auth.principal(request.session['user_id'])
            except AccessDenied:
                request.session.clear()
                request.session['csrf_token'] = secrets.token_urlsafe(32)
        return {'principal': principal, 'csrf_token': request.session['csrf_token'],
                'demo_mode': request.app.state.settings.demo_mode,
                'personas': list(PERSONAS) if request.app.state.settings.demo_mode else []}

    @app.post('/api/demo/session')
    async def change_session(body: DemoSession, request: Request):
        if not request.app.state.settings.demo_mode or not _loopback(request) or body.user_id not in PERSONAS:
            _denial(request, 'persona_unavailable')
            raise HTTPException(403, 'Persona unavailable')
        try:
            principal = request.app.state.auth.principal(body.user_id)
        except AccessDenied:
            _denial(request, 'persona_unavailable')
            raise HTTPException(403, 'Persona unavailable') from None
        _audit(request, principal, str(uuid.uuid4()), 'session_changed', {'status': 'success'})
        request.session.clear()
        request.session.update({'user_id': principal['id'], 'csrf_token': secrets.token_urlsafe(32)})
        return {'principal': principal, 'csrf_token': request.session['csrf_token']}

    @app.post('/api/queries')
    async def query(body: QueryRequest, request: Request):
        return await request.app.state.queries.query(_principal(request), body)

    @app.get('/api/sources/{version_id}/{chunk_id}')
    async def source(version_id: str, chunk_id: str, request: Request):
        return _read(request, 'source', lambda p: request.app.state.auth.source(p, version_id, chunk_id))

    @app.get('/api/policies/{document_id}/versions')
    async def history(document_id: str, request: Request):
        return _read(request, 'history', lambda p: request.app.state.auth.history(p, document_id))

    @app.get('/api/packets/{request_id}')
    async def packet(request_id: str, request: Request):
        return _read(request, 'packet', lambda p: request.app.state.queries.packet(p, request_id))

    @app.get('/api/packets/{request_id}/export')
    async def export(request_id: str, request: Request):
        value = _read(request, 'packet_export', lambda p: request.app.state.queries.packet(p, request_id))
        return JSONResponse(value, headers={'Content-Disposition': 'attachment; filename="evidence-packet.json"'})

    @app.get('/api/audit/events')
    async def audit_events(request: Request, limit: int = Query(default=50, ge=1, le=100),
                           offset: int = Query(default=0, ge=0, le=1000000),
                           request_id: str | None = Query(default=None, max_length=128,
                                                         pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:@/-]*$')):
        principal = _principal(request)
        if 'audit' not in principal['roles']:
            _audit(request, principal, str(uuid.uuid4()), 'access_denied', {'status': 'denied'})
            raise HTTPException(403, 'Audit access required')
        if not 1 <= limit <= 100:
            raise HTTPException(422, 'Invalid request fields')
        def read_audit(p):
            if 'audit' not in p['roles']:
                raise AccessDenied('Audit access required')
            events = request.app.state.audit.events(p['tenant_id'], limit=limit, offset=offset,
                                                    request_id=request_id)
            safe_keys = {'event_id', 'sequence', 'timestamp', 'request_id', 'principal_id',
                         'event_type', 'previous_hmac', 'current_hmac'}
            safe = [{key: value for key, value in event.items() if key in safe_keys} for event in events]
            return {'events': safe, 'integrity': request.app.state.audit.verify(p['tenant_id']),
                    'offset': offset, 'limit': limit,
                    'next_offset': offset + limit if len(events) == limit else None}
        return _read(request, 'audit_view', read_audit)

    @app.get('/', response_class=HTMLResponse)
    @app.get('/sources', response_class=HTMLResponse)
    @app.get('/policies', response_class=HTMLResponse)
    @app.get('/audit', response_class=HTMLResponse)
    async def page(request: Request):
        view = {'/': 'ask', '/sources': 'sources', '/policies': 'policies', '/audit': 'audit'}[request.url.path]
        return templates.TemplateResponse(request=request, name='index.html', context={'view': view})

    app.mount('/static', StaticFiles(directory=WEB / 'static'), name='static')
    return app


app = create_app()
