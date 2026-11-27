---
name: CommerceOps
description: Cross-border store analysis. Use CommerceOps tools for profit, ads, inventory, suppliers, competitors, price simulation, weekly reports, and SOP citations. Never invent figures. Stop at drafts for human approval.
user-invocable: true
argument-hint: '[store code] [question]'
allowed-tools: commerceops_list_stores,commerceops_profit_report,commerceops_ads_diagnosis,commerceops_inventory_risk,commerceops_supplier_comparison,commerceops_competitor_diff,commerceops_search_sops,simulate_price_change,generate_weekly_report,commerceops_create_ad_budget_draft,commerceops_create_purchase_order_draft,commerceops_create_competitor_response_draft
---

# CommerceOps

Use this skill for a cross-border store question about profit, advertising, stock, suppliers, or competitors.

The host may prefix tool names. Call the CommerceOps tool that matches the name below.

## Numbers

Before you state a profit, margin, ACOS, ROAS, TACOS, CTR, CVR, days of cover, reorder quantity, landed cost, or competitor delta, call the matching tool and use its JSON.

- Profit, margin, and the bridge: `commerceops_profit_report`
- Ads ratios and the budget ladder: `commerceops_ads_diagnosis`
- Cover, reorder point, and suggested units: `commerceops_inventory_risk`
- Supplier rank, MOQ, and lead-time risk: `commerceops_supplier_comparison`
- Price, BSR, rating, and complaint diffs: `commerceops_competitor_diff`
- A target list price, the new unit margin, profit delta, break-even ACOS, and the three elasticity scenarios: `simulate_price_change`
- The weekly profit bridge, ad cuts, stockouts, supplier ranks, competitor alerts, and approval counts: `generate_weekly_report`

If a value is null, say the status (`zero_net_sales`, `zero_attributed_sales`, `undefined_no_velocity`, `zero_units`, `negative_unit_margin`, and the others). Do not replace it with zero or with an estimate. Do not add ad spend twice. Order lines do not contain it.

`simulate_price_change` keeps ad spend at the observed window total. Quote its `elasticity_note` when you explain conservative, base, and optimistic. Optimistic means demand is less elastic.

`generate_weekly_report` copies engine output into JSON, Markdown, and a Feishu card. It does not create a draft. Pass `push_feishu` true only when the person asked to push. Without `FEISHU_WEBHOOK_URL` the card mode is `dry_run`. Do not add a combined total across currencies.

## SOP citations

When you explain a procedure, call `commerceops_search_sops`. Cite `doc_id`, `section`, and the returned `quote`. The quote is the only wording you may present as the SOP text.

## Drafts and approval

`commerceops_create_ad_budget_draft`, `commerceops_create_purchase_order_draft`, and `commerceops_create_competitor_response_draft` only store drafts.

After a draft is created, stop. Tell the person the draft id, the decision, and that execution waits for approval on the CommerceOps 经营 page. This server does not provide an approve or execute tool. Do not claim a budget, purchase order, or listing change has been applied until the approval page says the draft status is `executed`. A `replayed: true` result means the earlier execution still stands and was not repeated.
