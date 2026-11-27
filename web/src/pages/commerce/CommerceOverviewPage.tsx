import { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/common/EmptyState';
import {
  COMMERCE_PERIOD,
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

const STORES = [
  { code: 'us-main', label: '美国站 us-main' },
  { code: 'uk-main', label: '英国站 uk-main' },
];

const SCENARIO_LABEL: Record<string, string> = {
  conservative: '保守',
  base: '基准',
  optimistic: '乐观',
};

export function CommerceOverviewPage() {
  const { online, epoch } = useCommerceConnection();
  const loadedStore = useRef<string | null>(null);
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
    const requestStore = store;
    if (loadedStore.current !== requestStore) {
      setProfit(null);
      setAds(null);
      setInventory(null);
      setSuppliers({});
      setCompetitors(null);
      setPriceSim(null);
      setWeekly(null);
    }
    try {
      const info = await commerce<CommerceMeta>('/meta');
      setMeta(info);
      if (!info.online) {
        setOffline(true);
        return;
      }
      setOffline(false);
      const query = `store_code=${store}&start_date=${COMMERCE_PERIOD.start}&end_date=${COMMERCE_PERIOD.end}`;
      const [profitBody, adsBody, inventoryBody] = await Promise.all([
        commerce<ProfitReport>(`/api/v1/profit?${query}`),
        commerce<AdsReport>(`/api/v1/ads?${query}`),
        commerce<InventoryReport>(
          `/api/v1/inventory?store_code=${store}&as_of=${COMMERCE_PERIOD.asOf}&horizon_days=14`,
        ),
      ]);
      setProfit(profitBody);
      setAds(adsBody);
      setInventory(inventoryBody);
      const quotes = await Promise.all(
        inventoryBody.at_risk_skus.map(async (item) => {
          const report = await commerce<SupplierReport>(
            `/api/v1/suppliers/compare?store_code=${store}&sku=${item}&as_of=${COMMERCE_PERIOD.asOf}`,
          );
          return [item, report] as const;
        }),
      );
      setSuppliers(Object.fromEntries(quotes));
      if (store === 'us-main') {
        setCompetitors(
          await commerce<CompetitorReport>(
            `/api/v1/competitors/diff?store_code=${store}&sku=NS-LAMP-LED&as_of=${COMMERCE_PERIOD.asOf}`,
          ),
        );
      } else {
        setCompetitors(null);
      }
      loadedStore.current = requestStore;
      const codes = inventoryBody.skus.map((row) => row.sku);
      if (codes.length > 0) {
        setSku((current) => (codes.includes(current) ? current : codes[0]));
      }
    } catch (error) {
      setOffline(true);
      setMessage(errorText(error));
    } finally {
      setLoading(false);
    }
  }, [store]);

  useEffect(() => {
    void load();
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
            start_date: COMMERCE_PERIOD.start,
            end_date: COMMERCE_PERIOD.end,
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
          start_date: COMMERCE_PERIOD.start,
          end_date: COMMERCE_PERIOD.end,
          as_of: COMMERCE_PERIOD.asOf,
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
  const competitorAlerts = (competitors?.comparisons ?? []).filter(
    (row) => row.alerts.length > 0,
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
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
          {STORES.map((item) => (
            <option key={item.code} value={item.code}>
              {item.label}
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
          重置演示数据
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
      {offline && !profit ? (
        <EmptyState
          title="CommerceOps 未连接"
          description={
            message || '启动 Python 服务后再刷新。已有草案会留在数据库里。'
          }
        />
      ) : null}
      {profit && (
        <section
          className="rounded-xl border border-border bg-card/40 p-4"
          aria-label="利润桥"
        >
          <h2 className="text-sm font-medium">近 7 天利润</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {profit.currency} 本期 {money(profit.current.net_profit)}，上期{' '}
            {money(profit.previous?.net_profit)}，差额{' '}
            {money(profit.bridge?.delta_net_profit)}。桥接恒等式{' '}
            {profit.bridge?.identity_ok ? '成立' : '不成立'}。 销量{' '}
            {profit.units_sold}。
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
                  <td className="py-2">{row.code}</td>
                  <td className="py-2">{money(row.contribution)}</td>
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
            广告花费 {money(ads.total_ad_spend)}，商品销售额{' '}
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
                  <th className="py-2 font-medium">活动</th>
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
                        ({row.budget.reason})
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
          <h2 className="text-sm font-medium">14 天内可能断货</h2>
          {inventory.at_risk_skus.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">
              没有落入 14 天覆盖窗口的 SKU。
            </p>
          ) : (
            <ul className="mt-3 flex flex-col gap-3 text-sm">
              {inventory.at_risk_skus.map((sku) => {
                const row = inventory.skus.find((item) => item.sku === sku);
                const top = suppliers[sku]?.rank.rankings[0];
                return (
                  <li key={sku} className="border-t border-border pt-3">
                    <p>
                      {sku} 覆盖{' '}
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
            {competitorAlerts.map((row) => (
              <li key={row.competitor_asin}>
                {row.competitor_asin}：{row.alerts.join(', ')}，价格变化{' '}
                {row.price_change}，来源 {row.source}
              </li>
            ))}
          </ul>
        </section>
      )}
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
      {meta && (
        <details className="text-sm text-muted-foreground">
          <summary className="cursor-pointer">MCP 与 Skill 注册</summary>
          <p className="mt-2">
            Skill <code>{meta.skill.path}</code> 已作为项目 Skill。下面的 stdio
            配置不会改动已有 MCP，需要时再添加 id{' '}
            <code>{meta.mcp_preset.id}</code>。
          </p>
          <pre className="mt-2 overflow-auto rounded-lg bg-muted p-3 text-xs text-foreground">
            {JSON.stringify(meta.mcp_preset, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
