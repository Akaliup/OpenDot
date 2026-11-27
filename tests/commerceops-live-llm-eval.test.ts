import { describe, expect, test } from 'vitest';

/**
 * Live LLM agent evaluation. This file must not pretend a model ran.
 * A scripted invocation-chain check lives in commerceops-proxy.test.ts and
 * the Python MCP tests. Those are not LLM evaluations.
 */
export function liveLlmAgentEvaluation(): {
  label: 'live_llm_agent_evaluation';
  executed: boolean;
  reason: string;
} {
  const enabled = process.env.COMMERCEOPS_RUN_LIVE_LLM === '1';
  const key = process.env.COMMERCEOPS_LIVE_LLM_API_KEY?.trim() ?? '';
  if (!enabled || !key) {
    return {
      label: 'live_llm_agent_evaluation',
      executed: false,
      reason: 'requires API key',
    };
  }
  return {
    label: 'live_llm_agent_evaluation',
    executed: false,
    reason: 'live model call was not executed',
  };
}

describe('CommerceOps live LLM evaluation', () => {
  test('is unexecuted when no live model call is available', () => {
    const report = liveLlmAgentEvaluation();
    expect(report.label).toBe('live_llm_agent_evaluation');
    expect(report.executed).toBe(false);
    expect(report.reason).toBe('requires API key');
  });
});
