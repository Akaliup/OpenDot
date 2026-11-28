import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../../stores/auth';
import { CommerceOffline } from './api';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/common/EmptyState';
import { type AuditEntry, type DraftRow, commerce, errorText } from './api';
import { useCommerceConnection } from './connection';

function decisionText(draft: DraftRow): string {
  const decision = draft.decision;
  if (typeof decision.to_daily_budget === 'string') {
    return `${String(decision.campaign_external_id)} 日预算 ${String(decision.from_daily_budget)} → ${decision.to_daily_budget}（${String(decision.reason)}）`;
  }
  if (typeof decision.supplier_code === 'string') {
    return `${String(decision.sku)} 向 ${decision.supplier_code} 采购 ${String(decision.quantity)}，到岸成本 ${String(decision.unit_landed_cost)}，交期风险 ${String(decision.lead_time_risk)}`;
  }
  if (Array.isArray(decision.actions)) {
    return decision.actions
      .map((item) => {
        const action = item as {
          competitor_asin?: string;
          alert?: string;
          detail?: string;
        };
        return `${action.competitor_asin ?? ''} ${action.alert ?? ''} ${action.detail ?? ''}`.trim();
      })
      .join('\n');
  }
  return JSON.stringify(decision);
}

export function CommerceApprovalsPage() {
  const { online, epoch } = useCommerceConnection();
  const canApprove = useAuthStore((s) =>
    s.hasPermission('approve_commerceops'),
  );
  const [status, setStatus] = useState('all');
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [params] = useSearchParams();
  const requested = params.get('draft');
  const [selected, setSelected] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [message, setMessage] = useState('');
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (preserveMessage = false) => {
    if (!preserveMessage) setMessage('');
    try {
      const body = await commerce<{ drafts: DraftRow[] }>('/api/v1/drafts');
      setDrafts(body.drafts);
      setOffline(false);
      setSelected((current) =>
        current && body.drafts.some((draft) => draft.draft_id === current)
          ? current
          : (body.drafts.find((draft) => draft.draft_id === requested)?.draft_id ?? body.drafts[0]?.draft_id ?? null),
      );
    } catch (error) {
      setOffline(error instanceof CommerceOffline);
      setMessage(errorText(error));
    }
  }, [requested]);

  useEffect(() => {
    void load();
  }, [load, epoch]);

  useEffect(() => {
    if (!selected) {
      setAudit([]);
      return;
    }
    let active = true;
    setAudit([]);
    void commerce<{ entries: AuditEntry[] }>(`/api/v1/drafts/${encodeURIComponent(selected)}/audit`)
      .then((body) => { if (active) setAudit(body.entries); })
      .catch((error) => { if (active) setMessage(errorText(error)); });
    return () => { active = false; };
  }, [selected]);

  async function decide(kind: 'approve-and-execute' | 'reject') {
    if (!selected) return;
    setBusy(true);
    setMessage('');
    try {
      await commerce(`/api/v1/drafts/${selected}/${kind}`, {
        method: 'POST',
        body: JSON.stringify({
          note:
            kind === 'reject'
              ? 'Rejected in CommerceOps'
              : 'Approved in CommerceOps',
        }),
      });
      setMessage(
        kind === 'reject'
          ? '已拒绝，没有写入经营数据。'
          : '已批准并执行。再次批准只会记一条重放，不会重复写入。',
      );
      await load(true);
      const body = await commerce<{ entries: AuditEntry[] }>(
        `/api/v1/drafts/${selected}/audit`,
      );
      setAudit(body.entries);
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  const current = drafts.find((draft) => draft.draft_id === selected) ?? null;
  const pending = drafts.filter((draft) => draft.status === 'draft');
  const paused = online === false || offline;

  if (paused && drafts.length === 0) {
    return (
      <EmptyState
        title="CommerceOps 未连接"
        description={message || '草案还在数据库里。服务恢复后会回到这里。'}
      />
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <section aria-label="草案列表">
        <h2 className="text-sm font-medium">草案 {pending.length} 条待处理</h2>
        <label>
          状态{' '}
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setSelected(
                drafts.find(
                  (d) =>
                    e.target.value === 'all' || d.status === e.target.value,
                )?.draft_id ?? null,
              );
            }}
          >
            {Object.entries({
              all: '全部',
              draft: '待审批',
              approved: '已批准',
              rejected: '已拒绝',
              executed: '已执行',
            }).map(([v, t]) => (
              <option key={v} value={v}>
                {t}
              </option>
            ))}
          </select>
        </label>
        {message && !selected && <p role="status">{message}</p>}
        <ul className="mt-3 flex flex-col gap-2">
          {drafts.length === 0 && (
            <li className="text-sm text-muted-foreground">
              还没有草案。让智能体创建，或从概览看到异常后再生成。
            </li>
          )}
          {drafts
            .filter((d) => status === 'all' || d.status === status)
            .map((draft) => (
              <li key={draft.draft_id}>
                <button
                  type="button"
                  className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                    draft.draft_id === selected
                      ? 'border-primary bg-card'
                      : 'border-border'
                  }`}
                  onClick={() => setSelected(draft.draft_id)}
                >
                  <span className="block">{draft.action_type}</span>
                  <span className="text-muted-foreground">
                    {draft.status} · {draft.created_at}
                  </span>
                </button>
              </li>
            ))}
        </ul>
      </section>
      <section
        className="rounded-xl border border-border bg-card/40 p-4"
        aria-label="草案详情"
      >
        {!current ? (
          <p className="text-sm text-muted-foreground">选择一条草案。</p>
        ) : (
          <>
            <h2 className="text-sm font-medium">{current.action_type}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {current.status} · {current.created_by} · {current.draft_id}
            </p>
            <pre className="mt-3 whitespace-pre-wrap text-sm">
              {decisionText(current)}
            </pre>
            <p className="mt-2 text-sm">
              创建于 {current.created_at} · 操作者 {current.created_by}
            </p>
            <details className="my-3">
              <summary>影响、风险与数据证据</summary>
              <pre className="overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-xs">
                {JSON.stringify(current.evidence, null, 2)}
              </pre>
            </details>
            {!canApprove && (
              <p role="status">只读权限 · 请联系有审批权限的成员</p>
            )}
            {current.status === 'draft' || current.status === 'executed' ? (
              <div className="mt-4 flex gap-2">
                <Button
                  disabled={!canApprove || busy || paused}
                  onClick={() => void decide('approve-and-execute')}
                >
                  {current.status === 'executed' ? '再次批准' : '批准并执行'}
                </Button>
                {current.status === 'draft' && (
                  <Button
                    variant="destructive"
                    disabled={!canApprove || busy || paused}
                    onClick={() => void decide('reject')}
                  >
                    拒绝
                  </Button>
                )}
              </div>
            ) : null}
            {current.status === 'executed' && (
              <p className="mt-2 text-sm text-muted-foreground">
                再次批准只会记一条重放，采购单和预算修订不会再写一笔。
              </p>
            )}
            {message && (
              <p className="mt-3 text-sm text-muted-foreground" role="status">
                {message}
              </p>
            )}
            <h3 className="mt-6 text-sm font-medium">审计</h3>
            <table className="mt-2 w-full text-left text-sm">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-2 font-medium">时间</th>
                  <th className="py-2 font-medium">事件</th>
                  <th className="py-2 font-medium">操作者</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((entry) => (
                  <tr key={entry.id} className="border-t border-border">
                    <td className="py-2">{entry.created_at}</td>
                    <td className="py-2 whitespace-nowrap">
                      {entry.event}
                      {typeof entry.detail.reason === 'string' ? (
                        <span className="text-muted-foreground">
                          {' '}
                          ({entry.detail.reason})
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2">{entry.actor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  );
}
