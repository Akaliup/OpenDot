---
doc_id: sop-acos-optimization
title: Ad ACOS Optimization
version: "2026.03"
---

## Purpose

Use this procedure when advertising spend rises and conversion falls, or when ACOS crosses the operating ladder. Ratios come from formula ads.v1. A zero denominator is a named status, not a zero.

## Metric Definitions

ACOS is spend divided by attributed sales. ROAS is attributed sales divided by spend. TACOS is spend divided by the sales denominator supplied with the report: store TACOS uses store product sales (gross revenue minus discounts, refunds not removed), and a campaign TACOS uses that campaign's linked SKU sales. CTR is clicks over impressions. CVR is attributed orders over clicks. CPC is spend over clicks. CPA is spend over attributed orders.

## Anomaly Review

Flag a campaign as spend up and conversion down only when current spend is at least the policy minimum, current spend is greater than the previous window, and both CVR values exist and the current one is lower. Also flag ACOS at or above the high threshold and ACOS that worsened versus the previous window. A campaign whose spend and CVR are unchanged is not an anomaly, even if it spent a noticeable amount.

## Budget Cut Ladder

Apply one multiplier to the current daily budget. Severe ACOS, at or above 0.80, uses one half. High ACOS, at or above 0.40 and below 0.80, uses 0.70. A conversion decline that is not already in those ACOS bands uses 0.80. Otherwise leave the budget unchanged and do not open a draft.

Record control code acossevere and cut the daily budget in half when ACOS is at least 0.80.

The cut is a draft. It does not change the live daily budget. Execution waits for an approval record. Recompute the ladder at execution time; if the decision no longer matches, the draft is stale and must not be applied.

## What Not To Do

Do not compute ACOS by hand in the reply. Do not treat attributed sales summed across campaigns as unique store revenue. Do not raise a budget from this procedure.
