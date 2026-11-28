import { apiFetch, type ApiError } from '../../api/client';

export const COMMERCE_PERIOD = {
  start: '2026-03-08',
  end: '2026-03-14',
  asOf: '2026-03-15',
};

export class CommerceOffline extends Error {
  constructor() {
    super(
      'CommerceOps 服务未启动。先在 services/commerceops 运行 commerceops-api。',
    );
    this.name = 'CommerceOffline';
  }
}

function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'status' in error &&
    'message' in error
  );
}

export function errorText(error: unknown): string {
  if (error instanceof CommerceOffline) return error.message;
  if (isApiError(error) && error.status === 403)
    return '无权访问当前工作区或店铺，请切换工作区或联系管理员。';
  if (isApiError(error) && error.message === 'store_not_found')
    return '当前工作区没有此店铺，请刷新店铺列表。';
  if (isApiError(error)) return error.message || '请求失败';
  return '请求失败';
}

export async function commerce<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  try {
    return await apiFetch<T>(`/api/commerceops${path}`, options);
  } catch (error) {
    if (
      isApiError(error) &&
      (error.status === 0 || error.body?.code === 'commerceops_offline')
    )
      throw new CommerceOffline();
    throw error;
  }
}

export interface Ratio {
  value: string | null;
  status: string;
}

export interface ProfitReport {
  currency: string;
  units_sold: number;
  current: {
    net_profit: string;
    margin: string | null;
    margin_status: string;
    revenue: string;
    discounts: string;
    refunds: string;
    ad_spend: string;
  };
  previous: {
    revenue: string;
    discounts: string;
    margin: string | null;
    net_profit: string;
    refunds: string;
    ad_spend: string;
  } | null;
  bridge: {
    delta_net_profit: string;
    identity_ok: boolean;
    components: { code: string; contribution: string }[];
  } | null;
  drags: { code: string; contribution: string }[];
}

export interface AdsReport {
  total_sales: string;
  total_ad_spend: string;
  ad_sales: string;
  acos: Ratio;
  tacos: Ratio;
  campaigns: {
    campaign_external_id: string;
    name: string;
    sku: string | null;
    flags: string[];
    current: { spend: string; acos: Ratio; cvr: Ratio };
    budget: {
      reason: string;
      current_daily_budget: string;
      suggested_daily_budget: string;
    };
  }[];
}

export interface InventoryReport {
  at_risk_skus: string[];
  skus: {
    sku: string;
    at_risk: boolean;
    status: string;
    cover?: { available: number; days_of_cover: string | null; status: string };
    replenishment?: {
      suggested_order_qty: number | null;
      reorder_point: string | null;
    };
  }[];
}

export interface SupplierReport {
  rank: {
    status: string;
    rankings: {
      supplier_code: string;
      rank: number | null;
      landed_cost: string;
      adjusted_order_qty: number | null;
      lead_time_risk: string;
    }[];
  };
}

export interface CompetitorReport {
  sample_data: boolean;
  comparisons: {
    competitor_asin: string;
    alerts: string[];
    source: string;
    older_price?: string;
    newer_price?: string;
    newer_captured_at?: string;
    price_change_pct?: string;
    price_change: string;
  }[];
}

export interface DraftRow {
  draft_id: string;
  action_type: string;
  status: string;
  created_by: string;
  created_at: string;
  execution_ref: string | null;
  decision: Record<string, unknown>;
  evidence: Record<string, unknown>;
}

export interface AuditEntry {
  id: number;
  event: string;
  actor: string;
  created_at: string;
  detail: Record<string, unknown>;
}

export interface EvalCase {
  id: string;
  title: string;
  passed: boolean;
  formula_check: boolean;
  policy_guard: boolean;
  ops_minutes_saved: number;
  measured_model_tokens: number;
  estimated_relay_tokens: number;
  assertions: {
    name: string;
    passed: boolean;
    expected: string;
    actual: string;
  }[];
}

export interface Scorecard {
  generated_at: string;
  summary: {
    cases: number;
    passed: number;
    failed: number;
    ops_minutes_saved: number;
    measured_model_tokens: number;
    estimated_relay_tokens: number;
    token_note: string;
  };
  cases: EvalCase[];
}

export interface PriceScenario {
  name: string;
  elasticity: string;
  volume_multiplier: string;
  volume_status: string;
  units: string;
  period_profit: string;
  profit_delta: string;
}

export interface PriceSimulation {
  formula_version: string;
  sku: string;
  currency: string;
  status: string;
  current_price: string;
  target_price: string;
  new_unit_margin: { value: string | null; status: string };
  break_even_acos: { value: string | null; status: string };
  current_acos: { value: string | null; status: string };
  acos_headroom: string | null;
  profit_delta: string | null;
  baseline_period_profit: string | null;
  elasticity_note: string;
  scenarios: PriceScenario[];
}

export interface WeeklyReport {
  assembly: string;
  markdown: string;
  model_tokens: number;
  notification: { mode: string } | null;
  approvals: {
    pending: number;
    executed: number;
    rejected: number;
    purchase_orders: number;
  };
}

export interface CommerceMeta {
  stores: { code: string; name: string; currency: string; timezone: string }[];
  workspace_id: string;
  online: boolean;
  api_url: string;
  mcp_preset: {
    id: string;
    command: string;
    args: string[];
    description: string;
    env: Record<string, string>;
  };
  skill: { id: string; name: string; path: string };
}
