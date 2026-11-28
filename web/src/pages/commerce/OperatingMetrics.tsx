import { useState } from 'react';
import {
  LineChart,
  Line,
  Tooltip,
  XAxis,
  YAxis,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { Banknote, Boxes, Percent, ShoppingBag, Megaphone } from 'lucide-react';
import type { ProfitReport } from './api';

export interface Dashboard {
  daily: { day: string; sales: string; profit: string; spend: string }[];
  inventory_value: string | null;
  previous_inventory_value: string | null;
}
const metricLabels = { sales: '销售额', profit: '净利润', spend: '广告花费' };
type Metric = keyof typeof metricLabels;
export function OperatingMetrics({
  profit,
  data,
}: {
  profit: ProfitReport | null;
  data: Dashboard | null;
}) {
  const [metric, setMetric] = useState<Metric>('sales');
  const format = (value: unknown, percent: boolean) =>
    value == null
      ? '—'
      : new Intl.NumberFormat(
          'zh-CN',
          percent
            ? { style: 'percent', maximumFractionDigits: 1 }
            : {
                style: 'currency',
                currency: profit?.currency ?? 'USD',
                maximumFractionDigits: 2,
              },
        ).format(Number(value));
  const current = profit?.current,
    previous = profit?.previous;
  const cards = [
    {
      name: '总销售额',
      icon: ShoppingBag,
      a: current && Number(current.revenue) - Number(current.discounts),
      b: previous && Number(previous.revenue) - Number(previous.discounts),
    },
    {
      name: '净利润',
      icon: Banknote,
      a: current?.net_profit,
      b: previous?.net_profit,
    },
    {
      name: '净利润率',
      icon: Percent,
      a: current?.margin,
      b: previous?.margin,
    },
    {
      name: '广告花费',
      icon: Megaphone,
      a: current?.ad_spend,
      b: previous?.ad_spend,
    },
    {
      name: '库存价值',
      icon: Boxes,
      a: data?.inventory_value,
      b: data?.previous_inventory_value,
    },
  ];
  return (
    <>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        {cards.map(({ name, icon: Icon, a, b }) => {
          const change =
            a != null && b != null && Number(b) !== 0
              ? (Number(a) - Number(b)) / Math.abs(Number(b))
              : null;
          return (
            <article
              key={name}
              className="rounded-xl border bg-card p-4 shadow-sm"
            >
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                {name}
                <Icon size={17} />
              </div>
              <strong className="my-2 block text-xl tabular-nums">
                {format(a, name === '净利润率')}
              </strong>
              <small>
                上期 {format(b, name === '净利润率')} ·{' '}
                {change === null
                  ? '无可比值'
                  : change === 0 ? '持平' : (change < 0 ? '↓' : '↑') + format(Math.abs(change), true)}
              </small>
            </article>
          );
        })}
      </div>
      <section className="rounded-xl border bg-card p-5">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">经营趋势</h2>
          <div className="flex gap-2">
            {(Object.keys(metricLabels) as Metric[]).map((key) => (
              <button
                key={key}
                aria-pressed={metric === key}
                onClick={() => setMetric(key)}
                className={
                  metric === key
                    ? 'rounded-md bg-blue-600 px-3 py-1 text-white'
                    : 'rounded-md border px-3 py-1'
                }
              >
                {metricLabels[key]}
              </button>
            ))}
          </div>
        </div>
        {data?.daily.length ? (
          <ResponsiveContainer width="100%" height={210}>
            <LineChart
              data={data.daily.map((r) => ({ ...r, value: Number(r[metric]) }))}
            >
              <CartesianGrid vertical={false} strokeDasharray="3 4" />
              <XAxis dataKey="day" tickFormatter={(v) => String(v).slice(5)} />
              <YAxis width={58} />
              <Tooltip />
              <Line
                type="linear"
                dataKey="value"
                name={metricLabels[metric]}
                stroke="#2563eb"
                strokeWidth={3}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p>暂无趋势记录</p>
        )}
      </section>
    </>
  );
}
