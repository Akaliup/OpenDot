import { describe, expect, test } from 'vitest';
import {
  COMMERCEOPS_MCP_PRESET,
  forwardCommerceOps,
  upstreamPath,
} from '../src/routes/commerceops.js';

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
});
