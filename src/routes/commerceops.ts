/**
 * Authenticated proxy to the local CommerceOps FastAPI service.
 * The Python process is optional: a refused connection becomes 503.
 */
import { Hono } from 'hono';
import { authMiddleware } from '../middleware/auth.js';
import type { Variables } from '../web-context.js';

export const COMMERCEOPS_PREFIX = '/api/commerceops';
export const DEFAULT_COMMERCEOPS_API_URL = 'http://127.0.0.1:8077';

export const COMMERCEOPS_MCP_PRESET = {
  id: 'commerceops',
  command: 'commerceops-mcp',
  args: [] as string[],
  description:
    'Deterministic CommerceOps tools. Draft tools do not change budgets, purchase orders, or competitor snapshots.',
  env: {
    COMMERCEOPS_DATABASE_URL: 'sqlite:///./services/commerceops/commerceops.db',
  },
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

commerceopsRoutes.get('/meta', async (c) => {
  const baseUrl = commerceOpsBaseUrl();
  const health = await forwardCommerceOps({
    method: 'GET',
    path: '/health',
    search: '',
    baseUrl,
    timeoutMs: 2_000,
  });
  return c.json({
    online: health.status === 200,
    api_url: baseUrl,
    mcp_preset: COMMERCEOPS_MCP_PRESET,
    skill: {
      id: 'commerceops',
      name: 'CommerceOps',
      path: 'container/skills/commerceops/SKILL.md',
    },
  });
});

commerceopsRoutes.all('/*', async (c) => {
  const url = new URL(c.req.url);
  const method = c.req.method;
  const result = await forwardCommerceOps({
    method,
    path: upstreamPath(url.pathname),
    search: url.search,
    body:
      method === 'GET' || method === 'HEAD'
        ? undefined
        : await c.req.arrayBuffer(),
    contentType: c.req.header('content-type'),
    baseUrl: commerceOpsBaseUrl(),
  });
  return new Response(result.body, {
    status: result.status,
    headers: { 'content-type': result.contentType },
  });
});

export default commerceopsRoutes;
