import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/common/EmptyState';
import { type Scorecard, CommerceOffline, commerce, errorText } from './api';
import { useCommerceConnection } from './connection';

type AgentCard = {
  model?: string;
  cases: {
    case_id: number | string;
    status: string;
    failure_reason?: string;
    latency_ms?: number;
    actual_model_call?: boolean;
    model_calls?: number;
  }[];
  summary?: {
    called: number;
    passed: number;
    skipped: number;
    total_tokens: number;
  };
};

export function CommerceEvalPage() {
  const { online, epoch } = useCommerceConnection();
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [live, setLive] = useState<AgentCard | null>(null);
  const [scripted, setScripted] = useState<AgentCard | null>(null);
  const [missing, setMissing] = useState(false);
  const [offline, setOffline] = useState(false);
  const [message, setMessage] = useState('');
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setMessage('');
    try {
      const body = await commerce<{
        scorecard: Scorecard | null;
        scripted: AgentCard | null;
        live: AgentCard | null;
      }>('/api/v1/evals/latest');
      setScorecard(body.scorecard);
      setLive(body.live);
      setScripted(body.scripted);
      setMissing(body.scorecard == null);
      setOffline(false);
    } catch (error) {
      setOffline(error instanceof CommerceOffline);
      setMessage(errorText(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, epoch]);

  async function run() {
    setRunning(true);
    setMessage('');
    try {
      setScorecard(
        await commerce<Scorecard>('/api/v1/evals/run', {
          method: 'POST',
          timeoutMs: 120_000,
        }),
      );
      setMissing(false);
      setOffline(false);
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setRunning(false);
    }
  }

  if (offline && !scorecard)
    return <EmptyState title="CommerceOps 未连接" description={message} />;

  const paused = online === false || offline;

  return (
    <div className="flex flex-col gap-6">
      {(
        [
          ['DeepSeek Live LLM Evaluation', live],
          ['Scripted Agent Integration Evaluation', scripted],
        ] as const
      ).map(([title, card]) => (
        <section key={title} className="rounded-xl border border-border p-4">
          <h2 className="font-medium">{title}</h2>
          {card ? (
            <>
              <p>
                总数 {card.cases.length} · 通过{' '}
                {card.cases.filter((c) => c.status === 'passed').length} · 失败{' '}
                {
                  card.cases.filter((c) =>
                    ['failed', 'failure', 'error'].includes(c.status),
                  ).length
                }{' '}
                · 跳过 {card.cases.filter((c) => c.status === 'skipped').length}
              </p>
              {card.summary?.called === 0 && (
                <p>真实模型未运行 · 调用 0 次 · 平均响应时间 —</p>
              )}
              {!card.summary && (
                <p>脚本化测试 · 模型调用 0 次 · 0 tokens · 未记录耗时</p>
              )}
              {card.summary && card.summary.called > 0 && (
                <p>
                  模型调用{' '}
                  {card.cases
                    .filter((c) => c.actual_model_call)
                    .every((c) => c.model_calls != null)
                    ? card.cases.reduce((n, c) => n + (c.model_calls ?? 0), 0)
                    : '未记录'}{' '}
                  次 · 平均案例耗时{' '}
                  {Math.round(
                    card.cases
                      .filter((c) => c.actual_model_call)
                      .reduce((n, c) => n + (c.latency_ms ?? 0), 0) /
                      card.summary.called,
                  )}{' '}
                  ms
                </p>
              )}
              {card.summary && (
                <p>
                  {card.model} · 实际调用 {card.summary.called} 个案例 · 跳过{' '}
                  {card.summary.skipped} · {card.summary.total_tokens} tokens
                  {card.summary.called > 0 &&
                    ` · 通过 ${card.summary.passed}/${card.summary.called}`}
                </p>
              )}
              <ul>
                {card.cases.map((item) => (
                  <li key={item.case_id}>
                    {item.case_id} · {item.status} {item.failure_reason}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>尚无评测记录</p>
          )}
        </section>
      ))}
      <h2 className="font-medium">Deterministic Engine Evaluation</h2>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void run()} disabled={running || paused}>
          {running ? '正在评测' : '运行确定性评测'}
        </Button>
        <Button
          variant="outline"
          onClick={() => void load()}
          disabled={running}
        >
          读取最近结果
        </Button>
      </div>
      {message && (
        <p className="text-sm text-muted-foreground" role="status">
          {message}
        </p>
      )}
      {missing && !scorecard ? (
        <EmptyState
          title="还没有记分卡"
          description="运行评测后，这里显示每个案例的公式和审批守卫结果。"
        />
      ) : null}
      {scorecard && (
        <>
          <section
            className="rounded-xl border border-border bg-card/40 p-4"
            aria-label="评测汇总"
          >
            <h2 className="text-sm font-medium">
              总数 {scorecard.summary.cases} · 通过 {scorecard.summary.passed} · 失败 {scorecard.summary.failed} ·
              跳过 {scorecard.summary.cases - scorecard.summary.passed - scorecard.summary.failed}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              规划估算运营时间 {scorecard.summary.ops_minutes_saved}{' '}
              分钟，不是实测节省。实测模型 token{' '}
              {scorecard.summary.measured_model_tokens}
              。若只由模型转述工具结果，上限{' '}
              {scorecard.summary.estimated_relay_tokens} token。
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {scorecard.summary.token_note}
            </p>
            <p className="text-sm text-muted-foreground">模型调用 0 次 · 未记录平均耗时</p>
            <p className="mt-1 text-xs text-muted-foreground">
              生成于 {scorecard.generated_at}
            </p>
          </section>
          <ul className="flex flex-col gap-3">
            {scorecard.cases.map((item) => (
              <li
                key={item.id}
                className="rounded-xl border border-border bg-card/40 p-4"
              >
                <h3 className="text-sm font-medium">
                  <span
                    className={
                      item.passed ? 'text-foreground' : 'text-destructive'
                    }
                  >
                    {item.passed ? '通过' : '失败'}
                  </span>
                  <span className="ml-2">{item.title}</span>
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.id}
                  {item.formula_check ? ' · 公式' : ''}
                  {item.policy_guard ? ' · 审批守卫' : ''} ·{' '}
                  {item.ops_minutes_saved} 分钟
                </p>
                <ul className="mt-2 text-sm">
                  {item.assertions.map((assertion) => (
                    <li
                      key={assertion.name}
                      className="border-t border-border py-1"
                    >
                      {assertion.passed ? '通过' : '失败'} {assertion.name}
                      ：期望 {assertion.expected}，实际 {assertion.actual}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
