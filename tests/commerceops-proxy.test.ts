import { afterEach, describe, expect, test, vi } from 'vitest';
import { Hono } from 'hono';
import * as db from '../src/db.js';
import * as context from '../src/web-context.js';
import { signSessionToken } from '../src/auth.js';
import routes from '../src/routes/commerceops.js';
import {
  COMMERCEOPS_MCP_PRESET,
  canonicalCommerceIdentity,
  forwardCommerceOps,
  signCommerceOpsIdentity,
  stripUntrustedCommerceBody,
  upstreamPath,
} from '../src/routes/commerceops.js';
import { hasPermission } from '../src/permissions.js';

describe('CommerceOps proxy', () => {
  test('maps the OpenDot prefix onto the Python service', () => {
    expect(upstreamPath('/api/commerceops/health')).toBe('/health');
    expect(upstreamPath('/api/commerceops/api/v1/profit')).toBe(
      '/api/v1/profit',
    );
    expect(upstreamPath('/api/commerceops')).toBe('/health');
  });

  test('returns a structured offline response when the fetch fails', async () => {
    const result = await forwardCommerceOps({
      method: 'GET',
      path: '/health',
      search: '',
      baseUrl: 'http://127.0.0.1:9',
      fetchImpl: async () => {
        throw new Error('connect refused');
      },
    });
    expect(result.status).toBe(503);
    expect(JSON.parse(result.body).code).toBe('commerceops_offline');
  });

  test('forwards method, path, query, and body', async () => {
    let seen = '';
    let method = '';
    let body = '';
    const result = await forwardCommerceOps({
      method: 'POST',
      path: '/api/v1/seed',
      search: '?store=us-main',
      body: new TextEncoder().encode('{}').buffer,
      contentType: 'application/json',
      baseUrl: 'http://127.0.0.1:8077',
      fetchImpl: async (url, init) => {
        seen = String(url);
        method = init?.method ?? '';
        body = new TextDecoder().decode(init?.body as ArrayBuffer);
        return new Response('{"ok":true}', {
          status: 201,
          headers: { 'content-type': 'application/json' },
        });
      },
    });
    expect(result.status).toBe(201);
    expect(seen).toBe('http://127.0.0.1:8077/api/v1/seed?store=us-main');
    expect(method).toBe('POST');
    expect(body).toBe('{}');
  });

  test('rejects a non-http base url', async () => {
    const result = await forwardCommerceOps({
      method: 'GET',
      path: '/health',
      search: '',
      baseUrl: 'file:///tmp/commerceops',
      fetchImpl: async () => {
        throw new Error('should not be called');
      },
    });
    expect(result.status).toBe(503);
  });

  test('the MCP preset is additive and does not name an existing server', () => {
    expect(COMMERCEOPS_MCP_PRESET.id).toBe('commerceops');
    expect(COMMERCEOPS_MCP_PRESET.command).toBe('commerceops-mcp');
    expect(COMMERCEOPS_MCP_PRESET.id).not.toBe('miniclaw');
  });

  test('signs the identity OpenDot forwards and strips client actor fields', () => {
    const payload = canonicalCommerceIdentity({
      userId: 'user-1',
      username: 'ada',
      workspaceId: 'ws-a',
      canApprove: false,
      exp: 1_700_000_000,
    });
    expect(payload).toBe(
      '{"can_approve":false,"exp":1700000000,"scope":"commerceops","user_id":"user-1","username":"ada","v":1,"workspace_id":"ws-a"}',
    );
    const token = signCommerceOpsIdentity(
      {
        userId: 'user-1',
        username: 'ada',
        workspaceId: 'ws-a',
        canApprove: false,
      },
      'test-signing-secret-32chars',
      1_700_000_000_000,
    );
    expect(
      token.startsWith(payload.replace('"exp":1700000000', '"exp":1700000060')),
    ).toBe(true);
    const stripped = stripUntrustedCommerceBody(
      new TextEncoder().encode(
        JSON.stringify({ approver: 'owner', created_by: 'owner', note: 'ok' }),
      ).buffer,
      'application/json',
    );
    expect(JSON.parse(new TextDecoder().decode(stripped))).toEqual({
      note: 'ok',
    });
    expect(
      hasPermission({ role: 'member', permissions: [] }, 'approve_commerceops'),
    ).toBe(false);
    expect(
      hasPermission({ role: 'admin', permissions: [] }, 'approve_commerceops'),
    ).toBe(true);
  });
});

describe('mounted approval route', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  test.each([
    ['anonymous', '', 401],
    ['member', '', 403],
    ['member', '?workspace_id=elsewhere', 403],
    ['approver', '?workspace_id=elsewhere', 403],
    ['approver', '', 200],
  ] as const)('%s approval %s returns %i', async (actor, query, status) => {
    vi.stubEnv('COMMERCEOPS_SIGNING_SECRET', 'route-test-only-secret');
    const upstream = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ status: 'executed' }));
    vi.stubGlobal('fetch', upstream);
    const token = 'test-session';
    vi.spyOn(context, 'getCachedSessionWithUser').mockReturnValue({
      user_id: 'one',
      username: actor,
      status: 'active',
      role: 'member',
      permissions: actor === 'approver' ? ['approve_commerceops'] : [],
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    } as NonNullable<ReturnType<typeof context.getCachedSessionWithUser>>);
    vi.spyOn(db, 'getUserHomeGroup').mockReturnValue({
      folder: 'home-one',
    } as NonNullable<ReturnType<typeof db.getUserHomeGroup>>);
    vi.spyOn(db, 'getJidsByFolder').mockReturnValue(['web:other']);
    vi.spyOn(db, 'getRegisteredGroup').mockReturnValue({
      folder: 'elsewhere',
      jid: 'web:other',
      is_home: true,
      created_by: 'other',
    } as NonNullable<ReturnType<typeof db.getRegisteredGroup>>);
    vi.spyOn(db, 'updateSessionLastActive').mockImplementation(() => {});
    const app = new Hono().route('/api/commerceops', routes);
    const headers = new Headers({ 'content-type': 'application/json' });
    if (actor !== 'anonymous')
      headers.set('cookie', 'miniclaw_session=' + signSessionToken(token));
    const response = await app.request(
      'https://example.org/api/commerceops/api/v1/drafts/d1/approve-and-execute' +
        query,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          approver: 'owner',
          workspace_id: 'elsewhere',
          note: 'review',
        }),
      },
    );
    expect(response.status).toBe(status);
    if (status === 200) {
      expect(upstream).toHaveBeenCalledTimes(1);
      const [, init] = upstream.mock.calls[0];
      expect(
        JSON.parse(new TextDecoder().decode(init?.body as ArrayBuffer)),
      ).toEqual({ note: 'review' });
      expect(
        new Headers(init?.headers).get('x-commerceops-identity'),
      ).toContain('"workspace_id":"home-one"');
    } else {
      expect(upstream).not.toHaveBeenCalled();
      if (status === 403)
        expect((await response.json()).code).toBe(
          query ? 'workspace_forbidden' : 'approval_forbidden',
        );
    }
  });
});
