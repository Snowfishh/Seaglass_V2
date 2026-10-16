"""Local demo HTTP boundary. Identity and every evidence read are server checked."""

import asyncio
import hmac
import ipaddress
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.sessions import SessionMiddleware

from aspire_brain.answers import QueryError, QueryService
from aspire_brain.audit import AuditError, AuditWriter, ProtectedAuditStore
from aspire_brain.audit.protected import DEFAULT_INQUIRY_LIMIT, MAX_INQUIRY_LIMIT
from aspire_brain.audit.retention import RetentionPolicy
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.config import HOSTED_PROVIDER_MODE, ConfigurationError, Settings
from aspire_brain.db import Database
from aspire_brain.models import QueryRequest
from aspire_brain.platforms.routing import detect_time_window
from aspire_brain.platforms.runtime import connector_runtime, fixture_runtime
from aspire_brain.providers import LIVE_PROVIDER_MODES, configured_provider
from aspire_brain.web.cases import (
    FINTECH_NOW,
    FINTECH_PERSONAS,
    fintech_fixture_root,
    fintech_history,
    fintech_lookup_suggestions,
    fintech_source,
    run_case,
    run_typed_query,
    typed_service,
)

WEB = Path(__file__).parent / 'web'
PERSONAS = ('employee', 'finance_lead', 'policy_admin', 'auditor', 'other_tenant', 'disabled',
            *FINTECH_PERSONAS, 'fintech_auditor', 'fintech_admin')
LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}


class DemoSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str


class TypedCaseQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: Annotated[str, Field(min_length=1, max_length=2000, pattern=r'\S')]


class UpstreamChange(BaseModel):
    """A platform-side change on the fixture source, made by a platform administrator."""
    model_config = ConfigDict(extra='forbid')
    action: Literal['apply_runbook_update', 'revoke_restricted', 'restore_restricted']
    principal_id: Literal['user-a', 'user-b'] = 'user-a'


def build_platform_runtime(settings: Settings):
    """The shared four-platform index for this process: the fixture bundle or real accounts."""
    if settings.platform_source == 'connectors':
        from aspire_brain.platforms.connected import load_connector_config, load_tokens

        if settings.connectors_config_path is None:
            raise RuntimeError('ASPIRE_CONNECTORS_CONFIG is required for the connectors source')
        root = settings.root or Path.cwd()
        config = load_connector_config(settings.connectors_config_path, project_root=root)
        return connector_runtime(config, load_tokens(config.tokens_path, project_root=root),
                                 sync_interval_seconds=settings.sync_interval_seconds,
                                 freshness_budget_seconds=settings.freshness_budget_seconds)
    return fixture_runtime(fintech_fixture_root(settings.root, settings.fixture_root),
                           start=FINTECH_NOW,
                           sync_interval_seconds=settings.sync_interval_seconds)


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
                    https_only=self.owner.state.settings.hosted_demo,
                )
            await self.sessions(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def _loopback(request):
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


def _forwarded_scheme(request):
    # Only the hosted demo trusts this header: its TLS-terminating proxy is the sole ingress.
    return request.headers.get('x-forwarded-proto', '').split(',')[0].strip().lower()


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
        def verify_snapshot():
            try:
                fresh = request.app.state.auth.principal(principal['id'])
                current = (fresh, request.app.state.auth.revisions(fresh))
            except AccessDenied:
                current = None
            if current != snapshot:
                raise HTTPException(409, 'Access or content changed; retry the request')
        verify_snapshot()
        metadata = {'status': 'success'}
        if event == 'source' and isinstance(value, dict):
            metadata = {**metadata, 'version_ids': [value['version_id']],
                        'chunk_ids': [value['chunk_id']]}
        _audit(request, principal, request_id, f'{event}_completed', metadata)
        verify_snapshot()
        return value
    except AccessDenied:
        _audit(request, principal, request_id, 'access_denied', {'status': 'denied'})
        _audit(request, principal, request_id, f'{event}_denied', {'status': 'denied'})
        raise HTTPException(404, 'Evidence unavailable') from None
    except HTTPException:
        _audit(request, principal, request_id, f'{event}_aborted', {'status': 'changed'})
        raise
    except Exception:
        _audit(request, principal, request_id, f'{event}_failed', {'status': 'failed'})
        raise


def _mode_context(request):
    """Describe the provider this process actually runs, so page labels never go stale."""
    provider = request.app.state.provider
    live = provider.mode in LIVE_PROVIDER_MODES
    return {'provider_mode': provider.mode, 'live_provider': live,
            'live_model': (f'{provider.config.model} via {provider.config.service}'
                           if live else None),
            'platform_source': request.app.state.platforms.source}


def create_app(settings: Settings | None = None, provider=None, platform_runtime=None):
    @asynccontextmanager
    async def lifespan(application):
        resolved = settings or Settings.load()
        database = Database(resolved.db_path)
        database.initialize()
        audit = AuditWriter(resolved.db_path, resolved.audit_key, witness=resolved.audit_witness())
        audit.initialize()
        try:
            audit.anchor_all()
        except AuditError:
            pass  # A conflicting head is reported by verification; it must not stop startup.
        application.state.settings = resolved
        application.state.db = database
        application.state.auth = AuthService(database)
        application.state.audit = audit
        application.state.protected_audit = None
        if resolved.payload_key is not None:
            protected = ProtectedAuditStore(
                resolved.db_path, resolved.payload_key, audit, application.state.auth,
                retention=RetentionPolicy(max_age_days=resolved.audit_retention_days,
                                          max_entries=resolved.audit_retention_max_entries))
            protected.initialize()
            application.state.protected_audit = protected
        application.state.provider = provider or configured_provider(
            resolved.provider_mode, runtime=resolved.provider_runtime,
            credential=resolved.provider_credential(),
            ledger_path=resolved.provider_ledger_path)
        if resolved.hosted_demo and application.state.provider.mode != HOSTED_PROVIDER_MODE:
            raise ConfigurationError(f'Hosted demo mode runs {HOSTED_PROVIDER_MODE} only')
        application.state.queries = QueryService(
            database, application.state.auth, audit, provider=application.state.provider,
            protected_audit=application.state.protected_audit)
        runtime = platform_runtime or build_platform_runtime(resolved)
        if application.state.provider.mode in LIVE_PROVIDER_MODES and runtime.source != 'fixture':
            raise ConfigurationError('The live model answers from the fictional fixture only')
        application.state.platforms = runtime
        tasks = []
        if runtime.source == 'connectors':
            # Real accounts are read off the request path; status shows "unknown" until done.
            tasks.append(asyncio.create_task(asyncio.to_thread(runtime.sync_all, 'startup')))
        if runtime.sync_interval_seconds:
            tasks.append(asyncio.create_task(runtime.run_forever()))
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title='Aspire Internal Brain — local demo', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=WEB / 'templates')

    @app.middleware('http')
    async def security_boundary(request, call_next):
        hosted = request.app.state.settings.hosted_demo
        try:
            if hosted and request.url.hostname not in request.app.state.settings.allowed_hosts:
                _denial(request, 'host_not_allowed')
                response = JSONResponse({'detail': 'Invalid host'}, status_code=400)
            elif not hosted and request.url.hostname not in LOOPBACK_HOSTS:
                _denial(request, 'invalid_host')
                response = JSONResponse({'detail': 'Invalid host'}, status_code=400)
            elif request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                # Behind the hosted demo's proxy the app sees plain HTTP while the browser's
                # Origin is HTTPS; there the forwarded scheme is used and must be HTTPS.
                scheme = _forwarded_scheme(request) if hosted else request.url.scheme
                token = request.session.get('csrf_token', '')
                supplied = request.headers.get('x-csrf-token', '')
                origin = urlsplit(request.headers.get('origin', ''))
                valid_origin = (origin.scheme == scheme and origin.netloc == request.url.netloc
                                and not origin.path and not origin.query and not origin.fragment)
                if hosted and scheme != 'https':
                    _denial(request, 'insecure_transport')
                    response = JSONResponse({'detail': 'Request verification failed'}, status_code=403)
                elif not token or not hmac.compare_digest(token.encode(), supplied.encode()) or not valid_origin:
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
        if hosted:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    app.add_middleware(ConfiguredSessions, owner=app)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        _denial(request, 'invalid_request')
        detail = 'Invalid inquiry fields' if request.url.path == '/api/audit/inquiry' else 'Invalid request fields'
        return JSONResponse({'detail': detail}, status_code=422)

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
        # A hosted demo is a shared public instance whose visitors all arrive through its proxy;
        # each browser session still picks its own persona.
        selector_allowed = _loopback(request) or request.app.state.settings.hosted_demo
        if not request.app.state.settings.demo_mode or not selector_allowed or body.user_id not in PERSONAS:
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
        runtime = request.app.state.platforms
        return _read(request, 'source', lambda p: (
            fintech_source(runtime, p, version_id, chunk_id)
            if p['tenant_id'] == runtime.tenant_id
            else request.app.state.auth.source(p, version_id, chunk_id)))

    @app.get('/api/lookup-suggestions')
    async def lookup_suggestions(request: Request):
        runtime = request.app.state.platforms
        return _read(request, 'lookup_suggestions', lambda p: (
            fintech_lookup_suggestions(runtime, p) if p['tenant_id'] == runtime.tenant_id
            else request.app.state.auth.lookup_suggestions(p)))

    @app.get('/api/policies/{document_id}/versions')
    async def history(document_id: str, request: Request):
        runtime = request.app.state.platforms

        def synced_at(platform):
            value = runtime.index.last_successful_sync.get(platform)
            return value.isoformat() if value else None
        return _read(request, 'history', lambda p: (
            fintech_history(runtime, p, document_id, synced_at)
            if p['tenant_id'] == runtime.tenant_id
            else request.app.state.auth.history(p, document_id)))

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
                                                         pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:@/-]*$'),
                           newest_first: bool = False):
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
                                                    request_id=request_id,
                                                    newest_first=newest_first)
            safe_keys = {'event_id', 'sequence', 'timestamp', 'request_id', 'principal_id',
                         'event_type', 'previous_hmac', 'current_hmac'}
            safe = [{key: value for key, value in event.items() if key in safe_keys} for event in events]
            return {'events': safe, 'integrity': request.app.state.audit.verify(p['tenant_id']),
                    'offset': offset, 'limit': limit,
                    'next_offset': offset + limit if len(events) == limit else None}
        return _read(request, 'audit_view', read_audit)

    @app.get('/api/audit/inquiry')
    async def audit_inquiry(request: Request,
                            subject_id: str | None = Query(
                                default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$'),
                            platform: str | None = Query(
                                default=None,
                                pattern=r'^(confluence|jira|slack|drive|policy_store)$'),
                            since: datetime = Query(), until: datetime = Query(),
                            parent_id: str | None = Query(default=None, max_length=128),
                            source_id: str | None = Query(default=None, max_length=128),
                            decision_mode: str = Query(default='retrieved',
                                                       pattern=r'^(retrieved|denied|any)$'),
                            limit: int = Query(default=DEFAULT_INQUIRY_LIMIT, ge=1,
                                               le=MAX_INQUIRY_LIMIT),
                            cursor: str | None = Query(default=None, max_length=4096)):
        principal = _principal(request)
        if 'audit' not in principal['roles']:
            _audit(request, principal, str(uuid.uuid4()), 'access_denied', {'status': 'denied'})
            raise HTTPException(403, 'Audit access required')
        protected = request.app.state.protected_audit
        if protected is None:
            raise HTTPException(503, 'Protected audit unavailable')
        try:
            return _read(request, 'officer_inquiry', lambda p: protected.inquire(
                p['id'], subject_id=subject_id, platform=platform, parent_id=parent_id,
                source_id=source_id, since=since, until=until,
                decision_mode=decision_mode, limit=limit, cursor=cursor))
        except ValueError:
            raise HTTPException(422, 'Invalid inquiry fields') from None

    @app.get('/')
    async def home():
        return RedirectResponse('/cases', status_code=307)

    @app.get('/ask', response_class=HTMLResponse)
    @app.get('/sources', response_class=HTMLResponse)
    @app.get('/policies', response_class=HTMLResponse)
    @app.get('/audit', response_class=HTMLResponse)
    async def page(request: Request):
        view = {'/ask': 'ask', '/sources': 'sources', '/policies': 'policies', '/audit': 'audit'}[request.url.path]
        return templates.TemplateResponse(request=request, name='index.html',
                                          context={'view': view, **_mode_context(request)})

    @app.get('/cases', response_class=HTMLResponse)
    async def cases_page(request: Request):
        return templates.TemplateResponse(request=request, name='cases.html',
                                          context=_mode_context(request))

    @app.post('/api/four-platform/queries')
    async def typed_case(body: TypedCaseQuery, request: Request):
        principal = _principal(request)
        runtime = request.app.state.platforms
        try:
            detect_time_window(body.question, runtime.clock.now())
        except ValueError:
            # Rejected before the query service runs, so record the attempt and its outcome here.
            request_id = str(uuid.uuid4())
            _audit(request, principal, request_id, 'query_attempt',
                   {'provider_mode': request.app.state.provider.mode})
            _audit(request, principal, request_id, 'query_rejected', {'error_code': 'invalid_time_window'})
            raise HTTPException(422, 'Time window must be between 1 and 365 days') from None
        try:
            return await run_typed_query(request.app.state.auth, request.app.state.audit,
                                         principal['id'], body.question,
                                         request.app.state.protected_audit, runtime=runtime,
                                         provider=request.app.state.provider)
        except QueryError:
            raise
        except AccessDenied:
            raise HTTPException(409, 'Access or content changed; retry the request') from None
        except Exception:
            # Do not leak internal exception text
            return JSONResponse({'detail': 'Case simulation unavailable'}, status_code=503)

    @app.get('/api/four-platform/packets/{request_id}')
    async def typed_packet(request_id: str, request: Request):
        """Re-open a saved four-platform answer; every cited source is checked again first."""
        runtime = request.app.state.platforms
        service = typed_service(request.app.state.auth, request.app.state.audit, runtime)
        return _read(request, 'packet', lambda p: service.packet(p['id'], request_id))

    def _platform_member(request):
        principal = _principal(request)
        if principal['tenant_id'] != request.app.state.platforms.tenant_id:
            _audit(request, principal, str(uuid.uuid4()), 'access_denied', {'status': 'denied'})
            raise HTTPException(403, 'Platform status unavailable')
        return principal

    def _platform_admin(request):
        principal = _platform_member(request)
        if 'platform_admin' not in principal['roles']:
            _audit(request, principal, str(uuid.uuid4()), 'access_denied', {'status': 'denied'})
            raise HTTPException(403, 'Platform administrator required')
        return principal

    @app.get('/api/four-platform/status')
    async def platform_status(request: Request):
        _platform_member(request)
        return _read(request, 'platform_status', lambda p: request.app.state.platforms.status())

    @app.post('/api/four-platform/sync')
    async def platform_sync(request: Request):
        principal = _platform_admin(request)
        runtime = request.app.state.platforms
        runs = await asyncio.to_thread(runtime.sync_all, 'manual')
        _audit(request, principal, str(uuid.uuid4()), 'platform_sync',
               {'operation': 'platform_sync', 'status': 'success',
                'outcome': 'completed' if all(run['outcome'] == 'completed' for run in runs)
                else 'incomplete', 'source_count': len(runs)})
        return {'runs': [{key: run.get(key) for key in ('platform', 'outcome', 'error', 'created',
                                                         'updated', 'deleted', 'acl_changes',
                                                         'watermark')} for run in runs],
                'status': runtime.status()}

    @app.post('/api/four-platform/upstream-changes')
    async def upstream_change(body: UpstreamChange, request: Request):
        principal = _platform_admin(request)
        runtime = request.app.state.platforms
        if runtime.source != 'fixture':
            raise HTTPException(409, 'Upstream changes are made on the platforms themselves')
        if body.action == 'apply_runbook_update':
            changed = runtime.apply_fixture_updates()
        else:
            changed = runtime.set_restricted_access(body.principal_id,
                                                    body.action == 'restore_restricted')
        _audit(request, principal, str(uuid.uuid4()), 'upstream_change',
               {'operation': body.action, 'status': 'success', 'changed_fields': changed})
        return {'action': body.action, 'changed': changed, 'status': runtime.status()}

    @app.post('/api/cases/{case_id}')
    async def case_result(case_id: str, request: Request):
        if case_id not in {"case_1", "case_2", "case_3", "case_4", "case_5", "case_6", "case_7"}:
            raise HTTPException(404, 'Case not found')
        principal = _principal(request)
        if case_id == 'case_5' and 'audit' not in principal['roles']:
            _audit(request, principal, str(uuid.uuid4()), 'access_denied', {'status': 'denied'})
            raise HTTPException(403, 'Audit access required')
        if case_id == 'case_5':
            protected = request.app.state.protected_audit
            if protected is None:
                raise HTTPException(503, 'Protected audit unavailable')
            now = datetime.now(UTC)
            inquiry = _read(request, 'officer_inquiry', lambda p: protected.inquire(
                p['id'], subject_id='employee', platform='confluence',
                parent_id='payment-gateway', since=now - timedelta(days=30), until=now))
            return {'query': "What did employee access in the payment-gateway Confluence space in the last 30 days?",
                    'principal': principal['id'], 'platforms': ['confluence'],
                    'status': 'answered' if inquiry['entries'] else 'no_matches',
                    'inquiry': inquiry}
        try:
            result = await run_case(request.app.state.auth, request.app.state.audit,
                                    case_id, principal['id'],
                                    request.app.state.protected_audit,
                                    provider=request.app.state.provider)
            # Strip internal state objects from JSON response
            return {key: value for key, value in result.items()
                    if key not in {'state', 'upstream'}}
        except Exception:
            # Do not leak internal exception text
            return JSONResponse({'detail': 'Case simulation unavailable'}, status_code=503)

    app.mount('/static', StaticFiles(directory=WEB / 'static'), name='static')
    return app


app = create_app()
