import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/common/EmptyState';
import { type Scorecard, commerce, errorText } from './api';
import { useCommerceConnection } from './connection';

export function CommerceEvalPage() {
  const { online, epoch } = useCommerceConnection();
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [missing, setMissing] = useState(false);
  const [offline, setOffline] = useState(false);
  const [message, setMessage] = useState('');
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setMessage('');
    try {
      const body = await commerce<{ scorecard: Scorecard | null }>(
        '/api/v1/evals/latest',
      );
      setScorecard(body.scorecard);
      setMissing(body.scorecard == null);
      setOffline(false);
    } catch (error) {
      setOffline(true);
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
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void run()} disabled={running || paused}>
          {running ? '正在评测' : '运行评测'}
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
              {scorecard.summary.passed}/{scorecard.summary.cases} 通过
              {scorecard.summary.failed > 0
                ? `，${scorecard.summary.failed} 失败`
                : ''}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              估计节省运营时间 {scorecard.summary.ops_minutes_saved}{' '}
              分钟。实测模型 token {scorecard.summary.measured_model_tokens}
              。若只由模型转述工具结果，上限{' '}
              {scorecard.summary.estimated_relay_tokens} token。
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {scorecard.summary.token_note}
            </p>
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
