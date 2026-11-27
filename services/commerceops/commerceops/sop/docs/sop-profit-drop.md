---
doc_id: sop-profit-drop
title: Profit Drop Investigation
version: "2026.03"
---

## Purpose

Use this procedure when a marketplace store's net profit falls versus the previous window of the same length. The profit figure comes from formula profit.v1. Do not type a profit number that the profit report did not return.

## Window And Store

Name the store code and the inclusive dates before any explanation. Compare that window with the immediately previous window of equal length. Keep each store in its own currency. Do not blend a USD store with a GBP store into one profit total.

## Order Of Evidence

Read, in this order: gross revenue, discounts, refund amount, recovered COGS, platform fees, shipping fees, and advertising spend. Advertising spend is the sum of ad metric rows for that store and window. Order lines do not carry an advertising amount, so do not add a second advertising figure from a campaign export.

## Profit Bridge

Explain the change with the profit bridge. The signed component contributions must add up to current net profit minus previous net profit. If they do not, stop and treat the report as failed rather than narrating a cause. Rank the negative contributions as the drags. Separate a volume story from a rate story: units can be flat while profit falls.

## Refund Spike Check

A refund spike is a profit drag even when gross revenue is stable. Record control code profitrefundspike and reconcile recovered COGS before blaming the ad account. Recovered COGS is only the cost of units that came back in sellable condition. Unsellable returns stay as a full profit hit.

本步骤称为退款尖峰核对。

Match each refund to a SKU. Call out the SKU whose refund amount jumped, and keep the other SKUs in the bridge so a single spike is not mistaken for a store-wide demand collapse.

## What Not To Do

Do not invent a margin when net sales are zero. The status is zero_net_sales and the margin is null. Do not describe a negative net sales window as a healthy margin. Do not recommend a budget or purchase change from this procedure; hand those to the advertising and replenishment procedures as drafts.
