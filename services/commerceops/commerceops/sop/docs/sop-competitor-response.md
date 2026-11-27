---
doc_id: sop-competitor-response
title: Competitor Price And Review Response
version: "2026.03"
---

## Purpose

Use this procedure to read imported competitor snapshots and to draft a response. The diff is formula competitor.v1. This procedure does not fetch listings, log into a marketplace, or bypass access controls.

## Snapshot Requirements

Every snapshot needs a competitor ASIN, a capture timestamp, a source name, and a collection method. Allowed collection methods are demo_seed, manual_import, and licensed_feed. A demo_seed snapshot must stay labeled as sample data. Two snapshots are required. One snapshot is insufficient_history and produces no alert.

## Price Drop Response

Compare the latest snapshot at or before the as-of date with the one before it. A price drop alerts when the percent change is at or below -3 percent. A BSR jump alerts when the rank number improves, meaning it gets smaller, by at least 200 places. A larger rank number is not a jump. A rating drop alerts at 0.2 stars or more. A complaint spike alerts when negative review hits rise by at least 10.

Record control code competitorpricedrop and answer a competitor price drop with a sourced snapshot diff.

Keep the source name, collection method, and both timestamps inside the action text. A zero starting price has status zero_base_price and does not emit a price-drop alert.

## Response Draft

Map each alert to one action code: review_price_and_coupon, defend_share_of_voice, harvest_competitor_weakness, or mine_negative_review_keywords. The draft stores those actions. It does not edit a listing, post a public reply, or change a price. Approval writes a competitor response record and leaves the snapshots unchanged.

## What Not To Do

Do not describe sample data as a live marketplace pull. Do not fill a missing snapshot with an assumed price or star rating. Do not scrape.
