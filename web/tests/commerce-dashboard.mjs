/** Run against a built local OpenDot frontend. Business requests use a disposable FastAPI database. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const service = fileURLToPath(
  new URL('../../services/commerceops/', import.meta.url),
);
const child = spawn(
  process.env.COMMERCEOPS_EVAL_PYTHON || 'python',
  ['tests/browser_api_fixture.py'],
  {
    cwd: service,
    env: { ...process.env, PYTHONUTF8: '1' },
    stdio: ['pipe', 'pipe', 'inherit'],
  },
);
const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
let queue = Promise.resolve();
let admin = true,
  missing = false;
function api(method, url, body = null) {
  const task = queue.then(async () => {
    child.stdin.write(
      JSON.stringify({ method, path: url, body, admin }) + '\n',
    );
    const line = await lines.next();
    if (line.done) throw Error('fixture exited');
    return JSON.parse(line.value);
  });
  queue = task.catch(() => {});
  return task;
}
const dir = path.resolve(
  process.env.COMMERCEOPS_SCREENSHOTS || 'test-results/commerceops',
);
fs.mkdirSync(dir, { recursive: true });
let browser;
try {
  browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 960 },
    serviceWorkers: 'block',
  });
  page.on('pageerror', (e) => console.error('Browser error', e.stack));
  page.setDefaultTimeout(20000);
  await page.route('**/api/**', async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    const endpoint = url.pathname.replace('/api/commerceops', '');
    let result;
    if (url.pathname.startsWith('/api/commerceops/')) {
      if (endpoint === '/meta') {
        const r = await api('GET', '/api/v1/stores');
        result = {
          status: 200,
          json: {
            online: true,
            workspace_id: 'browser-test',
            stores: r.json.stores,
            skill: { path: 'commerceops' },
            mcp_preset: { id: 'commerceops' },
          },
        };
      } else {
        if (missing && endpoint === '/api/v1/profit')
          url.searchParams.set('store_code', 'nonexistent');
        result = await api(req.method(), endpoint + url.search, req.postData());
      }
    } else {
      const json =
        url.pathname === '/api/auth/me'
          ? {
              user: {
                id: 'browser',
                username: 'tester',
                display_name: 'Tester',
                role: admin ? 'admin' : 'member',
                permissions: [],
              },
              setupStatus: { needsSetup: false },
            }
          : url.pathname === '/api/auth/status'
            ? { initialized: true }
            : {};
      result = url.pathname.startsWith('/api/auth/')
        ? { status: 200, json }
        : { status: 503, json: { error: 'unavailable in component fixture' } };
    }
    await route.fulfill(result);
  });
  const origin = process.env.COMMERCEOPS_TEST_ORIGIN || 'http://127.0.0.1:3000';
  await page.goto(origin + '/commerce');
  await page
    .getByText(/当前工作区还没有店铺/)
    .waitFor()
    .catch(async (e) => {
      console.error(
        page.url(),
        (await page.locator('body').innerText()).slice(0, 800),
      );
      throw e;
    });
  await page.screenshot({ path: path.join(dir, 'empty.png') });
  await page.getByRole('button', { name: '加载演示数据' }).click();
  await page.locator('#commerce-store').selectOption('us-main');
  await page
    .getByText(/682\.60/)
    .first()
    .waitFor();
  await page.getByText(/更新于/).waitFor();
  await page.screenshot({ path: path.join(dir, 'dashboard.png') });
  const start = page.getByLabel('开始', { exact: true });
  const end = page.getByLabel('结束', { exact: true });
  await start.fill('2020-01-01');
  await end.fill('2020-01-07');
  await page.getByText(/所选日期没有订单销售记录/).waitFor();
  await page.screenshot({ path: path.join(dir, 'empty-period.png') });
  await end.fill('2026-03-14');
  await start.fill('2026-03-08');
  await page.getByText(/682\.60/).first().waitFor();
  await page.getByRole('button', { name: '净利润', exact: true }).click();
  assert.equal(
    await page
      .getByRole('button', { name: '净利润', exact: true })
      .getAttribute('aria-pressed'),
    'true',
  );
  await page.locator('#commerce-store').selectOption('uk-main');
  await page.getByText(/GBP 本期/).waitFor();
  await page.locator('#commerce-store').selectOption('us-main');
  await page.getByText(/USD 本期/).waitFor();
  missing = true;
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.getByText(/当前工作区没有此店铺/).waitFor();
  assert.equal(
    await page.getByText('CommerceOps 未连接', { exact: true }).count(),
    0,
  );
  await page.getByRole('heading', { name: '高 ACOS / 转化下滑' }).waitFor();
  missing = false;
  await page.getByRole('button', { name: '生成调整草案' }).first().click();
  await page.getByText(/草案已创建/).waitFor();
  await page.getByRole('link', { name: /^审核 / }).first().click();
  await page.getByRole('button', { name: '批准并执行' }).waitFor();
  assert(await page.getByRole('button', { name: '批准并执行' }).isEnabled());
  await page.screenshot({ path: path.join(dir, 'approvals.png') });
  admin = false;
  await page.reload();
  await page.getByText(/只读权限/).waitFor();
  assert(await page.getByRole('button', { name: '批准并执行' }).isDisabled());
  await page.goto(origin + '/commerce/evals');
  for (const name of ['Deterministic Engine Evaluation', 'Scripted Agent Integration Evaluation', 'DeepSeek Live LLM Evaluation']) {
    await page.getByRole('heading', { name }).waitFor();
  }
  await page.getByText(/实际调用 .* 个案例/).waitFor();
  await page.screenshot({ path: path.join(dir, 'evaluations.png') });
  console.log(
    'PASS empty workspace, seeded dashboard, trend, store switch, missing store, partial data, draft creation, admin/member approval controls. Screenshots:',
    dir,
  );
} finally {
  await browser?.close();
  child.stdin.end();
  if (child.exitCode === null) await once(child, 'exit');
}
