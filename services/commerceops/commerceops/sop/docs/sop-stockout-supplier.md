---
doc_id: sop-stockout-supplier
title: Stockout And Supplier Selection
version: "2026.03"
---

## Purpose

Use this procedure to find SKUs that can stock out inside the horizon and to turn a supplier comparison into a purchase-order draft. Cover math is inventory.v1. Quote ranking is supplier.v1.

## Days Of Cover

Days of cover equal available units divided by average daily sales. Available units are on-hand minus reserved, and never negative. If reserved exceeds on-hand, the SKU is oversold and available is 0. Average daily sales are units ordered in the lookback window divided by the number of lookback days. The lookback ends the day before the snapshot date. Refunds are not subtracted; they are a profit topic, not a demand eraser.

When average daily sales are 0, days of cover are undefined. Do not store 0 and do not store infinity. The status is undefined_no_velocity, and the SKU is not marked at risk from a cover ratio.

## Reorder Point

Reorder point equals average daily sales times lead time plus safety stock. Record control code stockoutreorder because reorder point equals average daily sales times lead time plus safety stock.

When velocity is 0, leave the reorder point null. A safety-stock-only number would pretend demand was observed.

The unconstrained need is average daily sales times the sum of lead time and target cover days, plus safety stock, minus available units and confirmed inbound units. Suggested units are the ceiling of that need. Inbound quantity still reduces the need when the inbound ETA is after the stockout date; the late inbound is a risk flag, not a reason to ignore the receipt.

## Quote Ranking

Rank quotes with the published weights: 0.40 landed cost, 0.25 lead time, 0.20 MOQ fit, 0.15 on-time delivery. Landed cost is unit price times one plus the duty rate, plus freight per unit. Choose the price tier whose minimum quantity is the greatest tier that the buy quantity still reaches. Snap the quantity up to the order multiple, then up to MOQ. If the raw need is 0, the order quantity stays 0. MOQ must not create a purchase by itself.

On-time rate enters the score only when the sample size is at least 8. A smaller sample scores 0 on that component and is labeled insufficient_sample. Say the sample size next to any on-time figure. Lead time longer than days of cover is arrives_after_stockout.

## Purchase Draft

The inventory suggestion uses the snapshot planning lead time and stops before MOQ. The purchase draft uses the chosen supplier's lead time, tier, MOQ, and multiple. Default to the rank-1 supplier. Do not transmit the purchase order. Approval creates a simulated open order and an audit row.
