/**
 * Authenticated proxy to the local CommerceOps FastAPI service.
 * The Python process is optional: a refused connection becomes 503.
 */
import { createHmac } from 'node:crypto';
import { Hono } from 'hono';
import {
  getJidsByFolder,
  getRegisteredGroup,
  getUserHomeGroup,
} from '../db.js';
import { authMiddleware } from '../middleware/auth.js';
import { hasPermission } from '../permissions.js';
import type { AuthUser } from '../types.js';
import { canAccessGroup } from '../web-context.js';
import type { Variables } from '../web-context.js';

export const COMMERCEOPS_PREFIX = '/api/commerceops';
export const DEFAULT_COMMERCEOPS_API_URL = 'http://127.0.0.1:8077';

export const COMMERCEOPS_MCP_PRESET = {
  id: 'commerceops',
  command: 'commerceops-mcp',
  args: [] as string[],
  description:
    'Deterministic CommerceOps tools. Draft tools do not change budgets, purchase orders, or competitor snapshots.',
};

export interface ForwardInput {
  method: string;
  path: string;
  search: string;
  body?: ArrayBuffer;
  contentType?: string;
  baseUrl: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  extraHeaders?: Record<string, string>;
}

export interface ForwardResult {
  status: number;
  body: string;
  contentType: string;
}

export function commerceOpsBaseUrl(
  raw = process.env.COMMERCEOPS_API_URL,
): string {
  return raw && raw.trim() ? raw.trim() : DEFAULT_COMMERCEOPS_API_URL;
}

export function upstreamPath(pathname: string): string {
  const index = pathname.indexOf(COMMERCEOPS_PREFIX);
  const rest =
    index >= 0 ? pathname.slice(index + COMMERCEOPS_PREFIX.length) : pathname;
  if (!rest || rest === '/') return '/health';
  return rest.startsWith('/') ? rest : `/${rest}`;
}

export async function forwardCommerceOps(
  input: ForwardInput,
): Promise<ForwardResult> {
  let target: URL;
  try {
    const base = new URL(input.baseUrl);
    if (base.protocol !== 'http:' && base.protocol !== 'https:') {
      throw new Error('unsupported protocol');
    }
    const path = input.path.startsWith('/') ? input.path : `/${input.path}`;
    target = new URL(path, base);
    target.search = input.search;
  } catch {
    return offline();
  }
  const headers = new Headers();
  if (input.contentType) headers.set('content-type', input.contentType);
  for (const [key, value] of Object.entries(input.extraHeaders ?? {})) {
    headers.set(key, value);
  }
  const sendBody = input.method !== 'GET' && input.method !== 'HEAD';
  try {
    const response = await (input.fetchImpl ?? fetch)(target, {
      method: input.method,
      headers,
      body: sendBody ? input.body : undefined,
      signal: AbortSignal.timeout(input.timeoutMs ?? 20_000),
    });
    return {
      status: response.status,
      body: await response.text(),
      contentType: response.headers.get('content-type') || 'application/json',
    };
  } catch {
    return offline();
  }
}

const APPROVAL_ROUTE =
  /\/drafts\/[^/]+\/(?:approve-and-execute|reject|execute)$/;

export function commerceSigningSecret(
  raw = process.env.COMMERCEOPS_SIGNING_SECRET,
): string {
  return raw?.trim() ?? '';
}

export function canonicalCommerceIdentity(fields: {
  userId: string;
  username: string;
  workspaceId: string;
  canApprove: boolean;
  exp: number;
}): string {
  return JSON.stringify({
    can_approve: fields.canApprove,
    exp: fields.exp,
    scope: 'commerceops',
    user_id: fields.userId,
    username: fields.username,
    v: 1,
    workspace_id: fields.workspaceId,
  });
}

export function signCommerceOpsIdentity(
  fields: {
    userId: string;
    username: string;
    workspaceId: string;
    canApprove: boolean;
  },
  secret: string,
  nowMs = Date.now(),
): string {
  const payload = canonicalCommerceIdentity({
    ...fields,
    exp: Math.floor(nowMs / 1000) + 60,
  });
  const digest = createHmac('sha256', secret).update(payload).digest('hex');
  return `${payload}.${digest}`;
}

export function stripUntrustedCommerceBody(
  body: ArrayBuffer | undefined,
  contentType?: string,
): ArrayBuffer | undefined {
  if (!body || !contentType?.toLowerCase().includes('application/json')) {
    return body;
  }
  try {
    const parsed = JSON.parse(new TextDecoder().decode(body)) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return body;
    }
    const record = parsed as Record<string, unknown>;
    delete record.approver;
    delete record.actor;
    delete record.created_by;
    delete record.workspace_id;
    return new TextEncoder().encode(JSON.stringify(record)).buffer;
  } catch {
    return body;
  }
}

export function resolveCommerceWorkspace(
  user: { id: string; role: AuthUser['role'] },
  requested: string,
): string | null {
  const folder = requested.trim();
  if (!folder) return getUserHomeGroup(user.id)?.folder ?? null;
  for (const jid of getJidsByFolder(folder)) {
    const group = getRegisteredGroup(jid);
    if (group && canAccessGroup(user, group)) return group.folder;
  }
  return null;
}

function offline(): ForwardResult {
  return {
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({
      error: 'CommerceOps 服务未启动',
      code: 'commerceops_offline',
      message:
        'Start services/commerceops and set COMMERCEOPS_API_URL if it is not on 127.0.0.1:8077.',
    }),
  };
}

const commerceopsRoutes = new Hono<{ Variables: Variables }>();

commerceopsRoutes.use('*', authMiddleware);

commerceopsRoutes.all('/*', async (c) => {
  const user = c.get('user');
  const secret = commerceSigningSecret();
  if (secret.length < 16) {
    return c.json(
      {
        error: 'auth_not_configured',
        code: 'auth_not_configured',
        message: 'Set COMMERCEOPS_SIGNING_SECRET to at least 16 characters.',
      },
      503,
    );
  }
  const requested = c.req.query('workspace_id') ?? '';
  const workspaceId = resolveCommerceWorkspace(user, requested);
  if (!workspaceId) {
    return c.json(
      {
        error: 'workspace_forbidden',
        code: 'workspace_forbidden',
        message: 'No accessible workspace for this user.',
      },
      403,
    );
  }
  const url = new URL(c.req.url);
  const method = c.req.method;
  const path = upstreamPath(url.pathname);
  const canApprove = hasPermission(user, 'approve_commerceops');
  if (APPROVAL_ROUTE.test(path) && !canApprove) {
    return c.json(
      {
        error: 'approval_forbidden',
        code: 'approval_forbidden',
        message: 'This account cannot approve CommerceOps drafts.',
      },
      403,
    );
  }
  const contentType = c.req.header('content-type');
  const body =
    method === 'GET' || method === 'HEAD'
      ? undefined
      : stripUntrustedCommerceBody(await c.req.arrayBuffer(), contentType);
  const result = await forwardCommerceOps({
    method,
    path: path === '/meta' && method === 'GET' ? '/api/v1/stores' : path,
    search: url.search,
    body,
    contentType,
    baseUrl: commerceOpsBaseUrl(),
    extraHeaders: {
      'x-commerceops-identity': signCommerceOpsIdentity(
        {
          userId: user.id,
          username: user.username,
          workspaceId,
          canApprove,
        },
        secret,
      ),
    },
  });
  if (path === '/meta' && method === 'GET' && result.status === 200) {
    return c.json({
      online: true,
      stores: JSON.parse(result.body).stores,
      workspace_id: workspaceId,
      api_url: commerceOpsBaseUrl(),
      mcp_preset: {
        ...COMMERCEOPS_MCP_PRESET,
        env: {
          COMMERCEOPS_WORKSPACE_ID: workspaceId,
        },
      },
      skill: {
        id: 'commerceops',
        name: 'CommerceOps',
        path: 'container/skills/commerceops/SKILL.md',
      },
    });
  }
  return new Response(result.body, {
    status: result.status,
    headers: { 'content-type': result.contentType },
  });
});

export default commerceopsRoutes;
