import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { OperatingMetrics, type Dashboard } from './OperatingMetrics';
import { type DraftRow } from './api';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/common/EmptyState';
import {
  COMMERCE_PERIOD,
  CommerceOffline,
  type AdsReport,
  type CommerceMeta,
  type CompetitorReport,
  type InventoryReport,
  type PriceSimulation,
  type ProfitReport,
  type SupplierReport,
  type WeeklyReport,
  commerce,
  errorText,
} from './api';
import { useCommerceConnection } from './connection';

function money(value: string | null | undefined): string {
  if (value == null || value === '') return '—';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  const text = amount.toFixed(2);
  return text === '-0.00' ? '0.00' : text;
}

function ratio(value: string | null | undefined, status?: string): string {
  if (value == null || value === '') return status || '—';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  const text = amount.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  return text === '-0' ? '0' : text;
}

const SCENARIO_LABEL: Record<string, string> = {
  conservative: '保守',
  base: '基准',
  optimistic: '乐观',
};

export function CommerceOverviewPage() {
  const { online, epoch } = useCommerceConnection();
  const generation = useRef(0);
  const [period, setPeriod] = useState(COMMERCE_PERIOD);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [updated, setUpdated] = useState<string>();
  const [question, setQuestion] = useState('为什么美国站本期利润下降？');
  const [store, setStore] = useState('us-main');
  const [meta, setMeta] = useState<CommerceMeta | null>(null);
  const [profit, setProfit] = useState<ProfitReport | null>(null);
  const [ads, setAds] = useState<AdsReport | null>(null);
  const [inventory, setInventory] = useState<InventoryReport | null>(null);
  const [suppliers, setSuppliers] = useState<Record<string, SupplierReport>>(
    {},
  );
  const [competitors, setCompetitors] = useState<CompetitorReport | null>(null);
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [dataset, setDataset] = useState('orders');
  const [sku, setSku] = useState('NS-BOTTLE-1L');
  const [targetPrice, setTargetPrice] = useState('18.00');
  const [priceSim, setPriceSim] = useState<PriceSimulation | null>(null);
  const [weekly, setWeekly] = useState<WeeklyReport | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [reporting, setReporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setMessage('');
    const version = ++generation.current;
    const active = () => version === generation.current;
    const errors: string[] = [];
    setUpdated(undefined);
    setDashboard(null);
    setDrafts([]);
    setProfit(null);
    setAds(null);
    setInventory(null);
    setSuppliers({});
    setCompetitors(null);
    setPriceSim(null);
    setWeekly(null);
    try {
      const info = await commerce<CommerceMeta>('/meta');
      if (!active()) return;
      setMeta(info);
      setOffline(false);
      if (!info.stores.length) {
        setStore('');
        return;
      }
      if (!info.stores.some((item) => item.code === store)) {
        setStore(
          (info.stores.find((s) => s.code === 'us-main') ?? info.stores[0])
            .code,
        );
        return;
      }
      const code = encodeURIComponent(store);
      const query = `store_code=${code}&start_date=${period.start}&end_date=${period.end}`;
      async function module<T>(
        label: string,
        url: string,
        apply: (data: T) => void | Promise<void>,
      ) {
        try {
          const data = await commerce<T>(url);
          if (active()) await apply(data);
        } catch (e) {
          errors.push(label + ' · ' + errorText(e));
        }
      }
      await Promise.all([
        module<Dashboard>('趋势', '/api/v1/dashboard?' + query, setDashboard),
        module<{ drafts: DraftRow[] }>('行动中心', '/api/v1/drafts', (r) =>
          setDrafts(r.drafts),
        ),
        module<ProfitReport>('利润', '/api/v1/profit?' + query, setProfit),
        module<AdsReport>('广告', '/api/v1/ads?' + query, setAds),
        module<InventoryReport>(
          '库存',
          `/api/v1/inventory?store_code=${code}&as_of=${period.asOf}`,
          async (data) => {
            setInventory(data);
            const skus = data.skus.map((row) => row.sku);
            setSku((current) =>
              skus.includes(current) ? current : (skus[0] ?? ''),
            );
            await Promise.all(
              data.at_risk_skus.map((item) =>
                module<SupplierReport>(
                  '供应商 ' + item,
                  `/api/v1/suppliers/compare?store_code=${code}&sku=${encodeURIComponent(item)}&as_of=${period.asOf}`,
                  (result) =>
                    setSuppliers((prev) => ({ ...prev, [item]: result })),
                ),
              ),
            );
            const reports: CompetitorReport[] = [];
            for (const item of skus) {
              if (!active()) return;
              await module<CompetitorReport>(
                '竞品 ' + item,
                `/api/v1/competitors/diff?store_code=${code}&sku=${encodeURIComponent(item)}&as_of=${period.asOf}`,
                (report) => {
                  reports.push(report);
                },
              );
            }
            if (active())
              setCompetitors({
                sample_data: reports.some((r) => r.sample_data),
                comparisons: reports.flatMap((r) => r.comparisons),
              });
          },
        ),
      ]);
      if (active()) {
        setUpdated(new Date().toLocaleTimeString());
        setMessage(errors.join('；'));
      }
    } catch (error) {
      if (active()) {
        setMeta(null);
        setOffline(error instanceof CommerceOffline);
        setMessage(errorText(error));
      }
    } finally {
      if (active()) setLoading(false);
    }
  }, [store, period]);

  useEffect(() => {
    void load();
    return () => {
      generation.current++;
    };
  }, [load, epoch]);

  async function resetSeed() {
    setMessage('');
    try {
      await commerce('/api/v1/seed', { method: 'POST', timeoutMs: 60_000 });
      setMessage('演示数据已重置。');
      await load();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function importCsv(file: File) {
    setMessage('');
    try {
      const text = await file.text();
      const result = await commerce<{ inserted: number; updated: number }>(
        `/api/v1/import/${dataset}`,
        {
          method: 'POST',
          body: text,
          headers: { 'Content-Type': 'text/csv' },
          timeoutMs: 60_000,
        },
      );
      setMessage(
        `已导入 ${dataset}：新增 ${result.inserted}，更新 ${result.updated}。`,
      );
      await load();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function sendBrief() {
    setMessage('');
    try {
      const result = await commerce<{
        brief: { alerts: unknown[] };
        notification: { mode: string } | null;
      }>(`/api/v1/notifications/anomalies?store_code=${store}`, {
        method: 'POST',
      });
      const mode = result.notification?.mode ?? 'none';
      setMessage(`异常 ${result.brief.alerts.length} 条，通知模式 ${mode}。`);
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function simulatePrice() {
    const price = targetPrice.trim();
    if (!price || !sku) {
      setMessage('先填写 SKU 和目标售价。');
      return;
    }
    setSimulating(true);
    setMessage('');
    try {
      const result = await commerce<PriceSimulation>(
        '/api/v1/price-simulations',
        {
          method: 'POST',
          body: JSON.stringify({
            store_code: store,
            sku,
            target_price: price,
            start_date: period.start,
            end_date: period.end,
          }),
        },
      );
      setPriceSim(result);
      setOffline(false);
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setSimulating(false);
    }
  }

  async function generateWeekly() {
    setReporting(true);
    setMessage('');
    try {
      const result = await commerce<WeeklyReport>('/api/v1/reports/weekly', {
        method: 'POST',
        body: JSON.stringify({
          start_date: period.start,
          end_date: period.end,
          as_of: period.asOf,
          push_feishu: true,
        }),
        timeoutMs: 60_000,
      });
      setWeekly(result);
      setOffline(false);
      const mode = result.notification?.mode ?? 'none';
      setMessage(`周报已生成，飞书模式 ${mode}。`);
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setReporting(false);
    }
  }

  const paused = online === false || offline;

  const flagged = (ads?.campaigns ?? []).filter(
    (row) => row.budget.reason !== 'no_adjustment',
  );
  const competitorAlerts = competitors?.comparisons ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-3">
        {meta && (
          <details className="relative">
            <summary className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-white">
              AI 经营分析助手
            </summary>
            <div className="absolute z-10 mt-2 grid w-72 gap-3 rounded-xl border bg-card p-4 shadow-lg">
              <label>
                经营问题
                <textarea
                  className="mt-2 w-full rounded-lg border p-2"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                />
              </label>
              <Link
                className="text-blue-600"
                state={{
                  commerceQuestion: `店铺 ${store} · ${period.start} 至 ${period.end} · 库存截至 ${period.asOf}。请引用 CommerceOps 工具证据。
${question}`,
                  commerceWorkspace: meta.workspace_id,
                }}
                to={'/chat/' + encodeURIComponent(meta.workspace_id)}
              >
                在工作区会话中继续
              </Link>
            </div>
          </details>
        )}
        <a
          href="#commerce-import"
          onClick={(e) => {
            e.preventDefault();
            document.getElementById('commerce-import')?.scrollIntoView();
          }}
        >
          导入 CSV
        </a>
        <label>
          开始{' '}
          <input
            type="date"
            value={period.start}
            max={period.end}
            onChange={(e) => {
              if (e.target.value)
                setPeriod({ ...period, start: e.target.value });
            }}
          />
        </label>
        <label>
          结束{' '}
          <input
            type="date"
            value={period.end}
            min={period.start}
            onChange={(e) => {
              if (e.target.value)
                setPeriod({
                  ...period,
                  end: e.target.value,
                  asOf: new Date(Date.parse(e.target.value) + 86400000)
                    .toISOString()
                    .slice(0, 10),
                });
            }}
          />
        </label>
        {updated && <small>更新于 {updated}</small>}
        {competitors?.sample_data && <small>含演示样本</small>}
        <label
          className="text-sm text-muted-foreground"
          htmlFor="commerce-store"
        >
          店铺
        </label>
        <select
          id="commerce-store"
          className="h-11 rounded-lg border border-border bg-background px-3 text-sm"
          value={store}
          onChange={(event) => setStore(event.target.value)}
        >
          {meta?.stores.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={loading ? 'motion-safe:animate-spin' : ''} />
          刷新
        </Button>
        <Button variant="outline" onClick={() => void resetSeed()}>
          {meta?.stores.length ? '重置演示数据' : '加载演示数据'}
        </Button>
        <Button
          variant="outline"
          onClick={() => void sendBrief()}
          disabled={paused}
        >
          飞书简报
        </Button>
        <Button
          variant="outline"
          onClick={() => void generateWeekly()}
          disabled={paused || reporting}
        >
          {reporting ? '正在生成周报' : '生成周报 / 推送飞书'}
        </Button>
      </div>
      {message && (
        <p className="text-sm text-muted-foreground" role="status">
          {message}
        </p>
      )}
      {loading && <p role="status">正在读取工作区经营数据…</p>}
      {!loading && meta?.stores.length === 0 && (
        <p role="status">
          当前工作区还没有店铺。可加载演示店铺，或请管理员配置店铺和 SKU 后导入 CSV。
        </p>
      )}
      {offline && !profit ? (
        <EmptyState
          title="CommerceOps 未连接"
          description={
            message || '启动 Python 服务后再刷新。已有草案会留在数据库里。'
          }
        />
      ) : null}
      {profit?.units_sold === 0 && !Number(profit.current.revenue) && (
        <p role="status" className="rounded-lg border bg-muted/30 p-4">
          所选日期没有订单销售记录。可调整日期或导入 CSV。
        </p>
      )}
      {store && (dashboard || profit) && (
        <OperatingMetrics profit={profit} data={dashboard} />
      )}
      <div className="grid items-start gap-4 xl:grid-cols-2 [&>section]:min-w-0 [&>section]:overflow-x-auto">
        {profit && (
          <section
            className="rounded-xl border border-border bg-card/40 p-4"
            aria-label="利润桥"
          >
            <h2 className="text-sm font-medium">
              利润归因 · {period.start} 至 {period.end}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              店铺时区 {meta?.stores.find((s) => s.code === store)?.timezone}。
              统计日 {period.asOf}。
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              {profit.units_sold === 0
                ? '数据不足。这个窗口没有可计算的销量。'
                : `${profit.currency} 本期 ${money(profit.current.net_profit)}，上期 ${money(profit.previous?.net_profit)}，差额 ${money(profit.bridge?.delta_net_profit)}。桥接恒等式 ${profit.bridge?.identity_ok ? '成立' : '不成立'}。 销量 ${profit.units_sold}。`}
            </p>
            <table className="mt-3 w-full text-left text-sm [&_td]:pr-4 [&_th]:pr-4">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-2 font-medium">因素</th>
                  <th className="py-2 font-medium">对利润的贡献</th>
                </tr>
              </thead>
              <tbody>
                {profit.bridge?.components.map((row) => (
                  <tr key={row.code} className="border-t border-border">
                    <td className="py-2">
                      {(
                        {
                          revenue: '销售收入',
                          discounts: '折扣',
                          refunds: '退款',
                          net_cogs: '商品成本',
                          platform_fees: '平台费用',
                          shipping_fees: '物流费用',
                          ad_spend: '广告成本',
                          other_fees: '其他费用',
                        } as Record<string, string>
                      )[row.code] ?? row.code}
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-3">
                        {money(row.contribution)}
                        <span
                          className={
                            Number(row.contribution) < 0
                              ? 'h-2 rounded bg-orange-400'
                              : 'h-2 rounded bg-blue-500'
                          }
                          style={{
                            width:
                              (Math.abs(Number(row.contribution)) /
                                Math.max(
                                  1,
                                  ...(profit.bridge?.components ?? []).map(
                                    (c) => Math.abs(Number(c.contribution)),
                                  ),
                                )) *
                                55 +
                              '%',
                          }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
        {ads && (
          <section
            className="rounded-xl border border-border bg-card/40 p-4"
            aria-label="广告异常"
          >
            <h2 className="text-sm font-medium">高 ACOS / 转化下滑</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              广告花费 {money(ads.total_ad_spend)}，广告销售额{' '}
              {money(ads.ad_sales)}，ACOS {ratio(ads.acos?.value)}，商品销售额{' '}
              {money(ads.total_sales)}，TACOS{' '}
              {ratio(ads.tacos.value, ads.tacos.status)}
            </p>
            {flagged.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">
                这个窗口没有需要削减的活动。
              </p>
            ) : (
              <table className="mt-3 w-full text-left text-sm [&_td]:pr-4 [&_th]:pr-4">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 font-medium">活动与证据</th>
                    <th className="py-2 font-medium">ACOS</th>
                    <th className="py-2 font-medium">建议预算</th>
                  </tr>
                </thead>
                <tbody>
                  {flagged.map((row) => (
                    <tr
                      key={row.campaign_external_id}
                      className="border-t border-border"
                    >
                      <td className="py-2 whitespace-nowrap">
                        {row.name}
                        <details className="text-xs">
                          <summary className="cursor-pointer text-blue-600">查看详情</summary>
                          <p>SKU {row.sku ?? '—'} · 花费 {money(row.current.spend)} · 转化率 {ratio(row.current.cvr.value, row.current.cvr.status)}</p>
                        </details>
                        <span className="text-muted-foreground">
                          {' '}
                          ({row.flags.join(', ')})
                        </span>
                      </td>
                      <td className="py-2 whitespace-nowrap">
                        {ratio(row.current.acos.value, row.current.acos.status)}
                      </td>
                      <td className="py-2 whitespace-nowrap">
                        {money(row.budget.current_daily_budget)} →{' '}
                        {money(row.budget.suggested_daily_budget)}
                        <span className="text-muted-foreground">
                          {' '}
                          ({row.budget.reason}){' '}
                          <button
                            className="text-blue-600"
                            onClick={async () => {
                              try {
                                await commerce('/api/v1/ads/budget-drafts', {
                                  method: 'POST',
                                  body: JSON.stringify({
                                    store_code: store,
                                    campaign_external_id:
                                      row.campaign_external_id,
                                    start_date: period.start,
                                    end_date: period.end,
                                  }),
                                });
                                await load();
                                setMessage('草案已创建，请前往审批中心。');
                              } catch (e) {
                                setMessage(errorText(e));
                              }
                            }}
                          >
                            生成调整草案
                          </button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )}
        {inventory && (
          <section
            className="rounded-xl border border-border bg-card/40 p-4"
            aria-label="库存与供应商"
          >
            <h2 className="text-sm font-medium">
              库存风险 · {inventory.skus.length} 个 SKU，
              {inventory.skus.filter((item) => item.cover && item.replenishment?.reorder_point != null &&
                item.cover.available < Number(item.replenishment.reorder_point)).length} 个低于补货点，
              {inventory.at_risk_skus.length} 个预计断货
            </h2>
            {inventory.at_risk_skus.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">
                没有识别到 14 天内的断货风险。
              </p>
            ) : (
              <ul className="mt-3 flex flex-col gap-3 text-sm">
                {inventory.at_risk_skus.map((sku) => {
                  const row = inventory.skus.find((item) => item.sku === sku);
                  const top = suppliers[sku]?.rank.rankings[0];
                  return (
                    <li key={sku} className="border-t border-border pt-3">
                      <p>
                        <span
                          className={
                            Number(row?.cover?.days_of_cover) <= 7
                              ? 'text-red-700'
                              : 'text-amber-700'
                          }
                        >
                          {Number(row?.cover?.days_of_cover) <= 7
                            ? '高风险'
                            : '预警'}
                        </span>{' '}
                        · {sku} 覆盖{' '}
                        {row?.cover?.days_of_cover ?? row?.cover?.status}{' '}
                        天，建议量{' '}
                        {row?.replenishment?.suggested_order_qty ?? '—'}
                      </p>
                      <p className="text-muted-foreground">
                        {top
                          ? `首选 ${top.supplier_code}，到岸成本 ${top.landed_cost}，采购量 ${top.adjusted_order_qty}，交期风险 ${top.lead_time_risk}`
                          : '没有供应商报价'}
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
            {inventory.skus.filter((item) => !item.at_risk).map((item) => (
              <p key={item.sku} className="mt-2 text-sm">
                {item.sku} · {item.cover?.days_of_cover != null
                  ? <span className="text-green-700">正常 · 覆盖 {item.cover.days_of_cover} 天</span>
                  : '库存快照或销量不足'}
              </p>
            ))}
          </section>
        )}
        {competitors && (
          <section
            className="rounded-xl border border-border bg-card/40 p-4"
            aria-label="竞品提醒"
          >
            <h2 className="text-sm font-medium">
              竞品快照 {competitors.sample_data ? '（演示样本）' : ''}
            </h2>
            <ul className="mt-3 flex flex-col gap-2 text-sm">
              {!competitorAlerts.length && <li>所选日期没有可用的竞品快照，可导入竞品 CSV。</li>}
              {competitorAlerts.map((row) => (
                <li key={row.competitor_asin}>
                  {row.competitor_asin}：{row.alerts.join(', ')}，价格变化{' '}
                  {row.price_change}（
                  {row.price_change_pct == null
                    ? '—'
                    : (Number(row.price_change_pct) * 100).toFixed(1) + '%'}
                  ），{money(row.older_price)} → {money(row.newer_price)} ·{' '}
                  {row.newer_captured_at} · {row.source}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
      <section
        className="rounded-xl border border-border bg-card/40 p-4"
        aria-label="价格模拟"
      >
        <h2 className="text-sm font-medium">价格模拟 price_sim.v1</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          目标售价按字符串进入计算。广告花费保持观察窗口的原值。乐观情景表示需求弹性更低。
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label
            className="text-sm text-muted-foreground"
            htmlFor="commerce-sku"
          >
            SKU
          </label>
          <select
            id="commerce-sku"
            className="h-11 rounded-lg border border-border bg-background px-3 text-sm"
            value={sku}
            onChange={(event) => setSku(event.target.value)}
          >
            {(inventory && inventory.skus.length > 0
              ? inventory.skus
              : [{ sku }]
            ).map((row) => (
              <option key={row.sku} value={row.sku}>
                {row.sku}
              </option>
            ))}
          </select>
          <label
            className="text-sm text-muted-foreground"
            htmlFor="commerce-target-price"
          >
            目标售价
          </label>
          <input
            id="commerce-target-price"
            className="h-11 w-32 rounded-lg border border-border bg-background px-3 text-sm"
            inputMode="decimal"
            value={targetPrice}
            onChange={(event) => setTargetPrice(event.target.value)}
          />
          <Button
            variant="outline"
            onClick={() => void simulatePrice()}
            disabled={paused || simulating}
          >
            {simulating ? '正在计算' : '计算价格'}
          </Button>
        </div>
        {priceSim && (
          <div className="mt-3 text-sm">
            <p>
              {priceSim.currency} {priceSim.current_price} →{' '}
              {priceSim.target_price}
              ，状态 {priceSim.status}。新单位毛利{' '}
              {ratio(
                priceSim.new_unit_margin.value,
                priceSim.new_unit_margin.status,
              )}
              ，基准情景利润变化 {money(priceSim.profit_delta)}，盈亏平衡 ACOS{' '}
              {ratio(
                priceSim.break_even_acos.value,
                priceSim.break_even_acos.status,
              )}
              ，当前 ACOS{' '}
              {ratio(priceSim.current_acos.value, priceSim.current_acos.status)}
              。
            </p>
            {priceSim.scenarios.length > 0 && (
              <table className="mt-3 w-full text-left text-sm [&_td]:pr-4 [&_th]:pr-4">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 font-medium">情景</th>
                    <th className="py-2 font-medium">弹性</th>
                    <th className="py-2 font-medium">销量倍数</th>
                    <th className="py-2 font-medium">利润变化</th>
                  </tr>
                </thead>
                <tbody>
                  {priceSim.scenarios.map((row) => (
                    <tr key={row.name} className="border-t border-border">
                      <td className="py-2">
                        {SCENARIO_LABEL[row.name] ?? row.name} {row.name}
                      </td>
                      <td className="py-2">{row.elasticity}</td>
                      <td className="py-2 whitespace-nowrap">
                        {row.volume_multiplier}
                        <span className="text-muted-foreground">
                          {' '}
                          ({row.volume_status})
                        </span>
                      </td>
                      <td className="py-2">{money(row.profit_delta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>
      {weekly && (
        <section
          className="rounded-xl border border-border bg-card/40 p-4"
          aria-label="周报"
        >
          <h2 className="text-sm font-medium">
            周报 {weekly.assembly}，飞书 {weekly.notification?.mode ?? '未推送'}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            待审批 {weekly.approvals.pending}，已执行{' '}
            {weekly.approvals.executed}
            ，采购单 {weekly.approvals.purchase_orders}，模型 token{' '}
            {weekly.model_tokens}。
          </p>
          <pre className="mt-3 overflow-auto whitespace-pre-wrap text-sm">
            {weekly.markdown}
          </pre>
        </section>
      )}
      <section
        className="rounded-xl border border-border bg-card/40 p-4"
        id="commerce-import"
        aria-label="导入"
      >
        <h2 className="text-sm font-medium">CSV 导入</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label
            className="text-sm text-muted-foreground"
            htmlFor="commerce-dataset"
          >
            数据集
          </label>
          <select
            id="commerce-dataset"
            className="h-11 rounded-lg border border-border bg-background px-3 text-sm"
            value={dataset}
            onChange={(event) => setDataset(event.target.value)}
          >
            {[
              'orders',
              'refunds',
              'ad_metrics',
              'inventory',
              'supplier_quotes',
              'competitor_snapshots',
            ].map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <input
            aria-label="选择 CSV 文件"
            className="text-sm"
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importCsv(file);
            }}
          />
        </div>
      </section>
      <section className="rounded-xl border bg-card p-5">
        <h2 className="font-semibold">行动中心</h2>
        <p>
          当前工作区 · 待审批{' '}
          {drafts.filter((d) => d.status === 'draft').length} · 已批准{' '}
          {drafts.filter((d) => d.status === 'approved').length} · 已拒绝{' '}
          {drafts.filter((d) => d.status === 'rejected').length} · 已执行{' '}
          {drafts.filter((d) => d.status === 'executed').length}
        </p>
        {drafts.filter((d) => d.status === 'draft').map((draft) => (
          <p key={draft.draft_id}>
            <Link className="text-blue-600" to={'/commerce/approvals?draft=' + encodeURIComponent(draft.draft_id)}>
              审核 {draft.action_type} · {draft.draft_id}
            </Link>
          </p>
        ))}
        {drafts
          .filter((d) => d.status === 'executed')
          .slice(0, 3)
          .map((d) => (
            <p key={d.draft_id}>
              {d.action_type} · {d.execution_ref}
            </p>
          ))}
        <Link className="text-blue-600" to="/commerce/approvals">
          查看草案、证据与执行记录
        </Link>
      </section>
      {meta && (
        <details className="text-sm text-muted-foreground">
          <summary className="cursor-pointer">MCP 与 Skill 注册</summary>
          <p className="mt-2">
            Skill <code>{meta.skill.path}</code> 已作为项目 Skill。下面的 stdio
            配置不会改动已有 MCP，需要时再添加 id{' '}
            <code>{meta.mcp_preset.id}</code>。在运行 MCP 的宿主中配置同一业务数据库的
            COMMERCEOPS_DATABASE_URL，并确认该工作区可以调用工具。
          </p>
          <pre className="mt-2 overflow-auto rounded-lg bg-muted p-3 text-xs text-foreground">
            {JSON.stringify(meta.mcp_preset, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
