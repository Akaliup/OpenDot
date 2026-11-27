// Run from the repository root: node --import tsx services/commerceops/evals/live_agent.mjs
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { ManagedMcpConnection } from '../../../src/mcp-client.ts';
import { mcpDigest } from '../../../src/mcp-contract.ts';
import { cases, allowed, draft, grade } from './live_cases.mjs';

const directory = path.dirname(fileURLToPath(import.meta.url));
const model = process.env.DEEPSEEK_MODEL || 'deepseek-chat';
const key = process.env.DEEPSEEK_API_KEY;
const base = process.env.DEEPSEEK_BASE_URL?.replace(/\/$/, '');
// Resolve the interpreter before launching the MCP child with a minimal environment.
function interpreter() {
  return execFileSync(
    process.env.COMMERCEOPS_EVAL_PYTHON || 'python',
    ['-c', 'import sys; print(sys.executable)'],
    { encoding: 'utf8' },
  ).trim();
}
const endpointOK = [
  'https://api.deepseek.com',
  'https://api.deepseek.com/v1',
].includes(base);
const missing =
  !key || !base
    ? 'DeepSeek environment configuration missing'
    : !endpointOK
      ? 'Expected official DeepSeek HTTPS endpoint'
      : '';
const generated_at = new Date().toISOString();
const rows = [];
const system =
  'You are a CommerceOps agent. Respond in English. Use only the supplied MCP tools for business facts. Quote tool values verbatim; do no financial arithmetic. Distinguish simulated scenarios from forecasts. Only a human can approve or execute. The demo US store is us-main, reporting window 2026-03-08 to 2026-03-14, inventory date 2026-03-15 unless the user specifies otherwise.';
let requests = 0;
let reservedBytes = 0;

async function run(id, spec, row, smoke) {
  const python = interpreter();
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'commerceops-eval-'));
  const filename = path.join(cwd, 'fixture.db');
  const sessionId = randomUUID();
  const env = {
    PYTHONUTF8: '1',
    COMMERCEOPS_DATABASE_URL: 'sqlite:///' + filename.replaceAll('\\', '/'),
    COMMERCEOPS_WORKSPACE_ID: 'eval',
    COMMERCEOPS_ACTOR: 'eval-agent',
  };
  if (process.platform === 'win32') env.SystemRoot = process.env.SystemRoot;
  const state = (action) =>
    JSON.parse(
      execFileSync(
        python,
        [path.join(directory, 'fixture.py'), action, filename],
        { cwd, env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
      ),
    );
  const tools = allowed.filter((n) => n !== draft || [3, 8].includes(id));
  const conn = new ManagedMcpConnection({
    ownerId: 'eval',
    serverId: 'commerceops',
    cwd,
    definition: {
      enabled: true,
      addedAt: '',
      command: python,
      args: ['-m', 'commerceops.mcp_server'],
      env,
      pi: { version: 1, enabled: true, location: { kind: 'host' }, tools },
    },
    authorizeStartup(scope) {
      if (scope.owner_id !== 'eval' || scope.server_id !== 'commerceops')
        throw Error('scope');
    },
  });
  try {
    const before = state('seed');
    const entries = await conn.ready();
    const catalog = entries.map(({ definition: d }) => ({
      type: 'function',
      function: {
        name: d.name,
        description: d.description,
        parameters: d.inputSchema,
      },
    }));
    const messages = [{ role: 'system', content: system }];
    for (const [turn, prompt] of spec.prompts.entries()) {
      messages.push({ role: 'user', content: prompt });
      let finished = false;
      for (let step = 0; step < 5; step++) {
        let message;
        if (smoke) {
          if (step > 0) break;
          message = {
            role: 'assistant',
            tool_calls: [
              {
                id: 'smoke',
                type: 'function',
                function: {
                  name: 'commerceops_order_summary',
                  arguments: JSON.stringify({
                    store_code: 'us-main',
                    start_date: '2026-03-08',
                    end_date: '2026-03-14',
                  }),
                },
              },
            ],
          };
        } else {
          const body = JSON.stringify({
            model,
            messages,
            tools: catalog,
            temperature: 0,
            max_tokens: 900,
          });
          const size = Buffer.byteLength(body);
          if (
            ++requests > 45 ||
            size > 70000 ||
            (reservedBytes += size) > 1100000
          )
            throw Error('budget limit');
          const response = await fetch(base + '/chat/completions', {
            method: 'POST',
            redirect: 'error',
            signal: AbortSignal.timeout(60000),
            headers: {
              'Content-Type': 'application/json',
              Authorization: 'Bearer ' + key,
            },
            body,
          });
          if (!response.ok) throw Error('DeepSeek HTTP ' + response.status);
          const data = await response.json();
          row.actual_model_call = true;
          for (const name of [
            'prompt_tokens',
            'completion_tokens',
            'total_tokens',
          ]) {
            if (!Number.isInteger(data.usage?.[name]))
              throw Error('usage unavailable');
            row[name] += data.usage[name];
          }
          message = data.choices[0].message;
        }
        messages.push(message);
        if (!message.tool_calls?.length) {
          row.answers.push(message.content ?? '');
          finished = true;
          break;
        }
        if (message.tool_calls.length > 5) throw Error('tool budget');
        for (const call of message.tool_calls) {
          const name = call.function.name;
          const args = JSON.parse(call.function.arguments);
          const entry = entries.find((e) => e.definition.name === name);
          row.tool_calls.push(name);
          row.tool_arguments.push(args);
          row.tool_turns.push(turn + 1);
          let result;
          if (!entry) {
            row.tool_results.push({ error: 'tool outside catalog' });
            throw Error('tool outside catalog');
          }
          if (id === 7 && name === 'commerceops_profit_report')
            result = { error: 'injected_unavailable' };
          else {
            const output = await conn.dispatch({
              intent: {
                ...entry.identity,
                operation: 'mcp.call',
                call_id: randomUUID(),
                dot_id: sessionId,
                workspace_jid: 'web:eval',
                session_id: sessionId,
                arguments_digest: mcpDigest(args),
                grant_id: sessionId,
                grant_revision: 1,
                cancel_generation: 0,
                expires_at: Date.now() + 10000,
                source: {
                  runtime: 'pi-coding-agent',
                  conversation_id: sessionId,
                  business_turn_id: String(turn),
                  tool_call_id: call.id,
                },
              },
              arguments: args,
              signal: AbortSignal.timeout(10000),
              recheck() {
                if (!tools.includes(name)) throw Error('scope');
              },
              markDispatched() {},
            });
            result = output.isError
              ? { error: 'tool_failed' }
              : JSON.parse(output.content[0].text);
          }
          row.tool_results.push(result);
          messages.push({
            role: 'tool',
            tool_call_id: call.id,
            content: JSON.stringify(result),
          });
        }
      }
      if (!finished && !smoke) throw Error('turn budget');
    }
    if (smoke) {
      if (!(row.tool_results[0]?.orders > 0)) throw Error('MCP smoke failed');
      return;
    }
    row.assertions = grade(id, row, before, state('snapshot'));
    row.passed = row.assertions.every((a) => a.passed);
    row.failure_reason =
      row.assertions
        .filter((a) => !a.passed)
        .map((a) => a.name)
        .join(', ') || null;
  } finally {
    await conn.close();
    fs.rmSync(cwd, { recursive: true, force: true });
  }
}

const smoke = process.argv.includes('--check-mcp');
for (const [i, spec] of cases.entries()) {
  const row = {
    case_id: i + 1,
    model,
    generated_at,
    prompt_version: 'commerceops-en-v1',
    actual_model_call: false,
    status: 'skipped',
    passed: null,
    failure_reason: missing || null,
    tool_calls: [],
    tool_arguments: [],
    tool_results: [],
    tool_turns: [],
    assertions: [],
    answers: [],
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    latency_ms: 0,
    estimated_cost: null,
  };
  if (!missing || smoke) {
    const start = performance.now();
    try {
      await run(i + 1, spec, row, smoke);
    } catch (error) {
      if (smoke) throw error;
      while (row.tool_results.length < row.tool_calls.length)
        row.tool_results.push({ error: 'dispatch_failed' });
      const safe =
        /^(budget limit|DeepSeek HTTP \d{3}|tool budget|turn budget|usage unavailable|tool outside catalog)$/;
      row.failure_reason = safe.test(error.message)
        ? error.message
        : 'Evaluation transport or tool failure';
      row.passed = row.actual_model_call ? false : null;
    }
    row.latency_ms = Math.round(performance.now() - start);
    row.status = row.actual_model_call
      ? row.passed
        ? 'passed'
        : 'failed'
      : 'skipped';
  }
  if (smoke) {
    console.log('Managed MCP order summary passed');
    break;
  }
  rows.push(row);
}
if (!smoke) {
  const called = rows.filter((r) => r.actual_model_call);
  const card = {
    model,
    generated_at,
    cases: rows,
    summary: {
      called: called.length,
      skipped: rows.length - called.length,
      passed: called.filter((r) => r.passed).length,
      total_tokens: rows.reduce((n, r) => n + r.total_tokens, 0),
    },
  };
  const serialized = JSON.stringify(card, null, 2);
  if (key && serialized.includes(key)) throw Error('Unsafe scorecard');
  fs.writeFileSync(
    path.join(directory, 'live_llm_scorecard.json'),
    serialized + '\n',
  );
  console.log(card.summary);
  if (
    rows.some(
      (r) => r.status === 'failed' || (!missing && r.status === 'skipped'),
    )
  )
    process.exitCode = 1;
}
