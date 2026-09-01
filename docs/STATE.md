# Current Project State (SvZ)

Last updated: 2026-08-31 17:59

```mermaid
flowchart TD
    classDef done fill:#2e7d32,stroke:#1b5e20,color:#fff,stroke-width:2px;
    classDef inprogress fill:#f57c00,stroke:#e65100,color:#fff,stroke-width:2px;
    classDef todo fill:#424242,stroke:#212121,color:#ddd,stroke-width:1px,stroke-dasharray: 5 5;
    classDef blocked fill:#c62828,stroke:#b71c1c,color:#fff,stroke-width:2px;

    S0["S0: Boundary evaluation harness"] :::done
    S1["S1: Zero-annotation diagnostics"] :::done
    S2["S2: Anchor phrase inventory"] :::done
    S3_tooling["S3-tooling: Boundary gold tooling"] :::done
    S3_annotation["S3-annotation: Manual boundary annotation"] :::done
    S4["S4: Segmentation assembly"] :::inprogress
    S5["S5: Evaluation and review routing"] :::inprogress
    S0 --> S5
    S1 --> S4
    S2 --> S4
    S3_tooling --> S3_annotation
    S3_annotation --> S5
    S4 --> S5
```

## Overall Progress

- [X] S0: Boundary evaluation harness — Implemented boundary P/R/F1 at tolerance t, WindowDiff/P_k, and exact-count satisfaction; gold-data adapter remains part of S4 evaluation.
- [X] S1: Zero-annotation diagnostics — D1, D1c, D2, and D2b completed; findings support segmentation-transfer framing.
- [X] S2: Anchor phrase inventory — Harvested 1626-1630 opening/closing phrases to output/s2_anchor_phrase_inventory.json.
- [X] S3-tooling: Boundary gold tooling — Built sample generator, annotation UI, and merge script. Upstream res_start has zero target-inventory overlap.
- [X] S3-annotation: Manual boundary annotation — All 50 days annotated and merged. Exception review distinguishes segmentable, cross-day-shift, and missing-HTR cases.

- [/] S4: Segmentation assembly — Held-out tier-1 opening candidates confirm missing phrase families; next integrate them as positional priors.
I’ll set up the workflow structure and begin `S4a` only: create the five guides under `docs/steps/`, add a linked checklist to `PLAN.md`, and make `S4a` the implementation-ready entry point for the session-date ledger.

Read , lines 1 to 30

The plan has no prior step index, so I’ll introduce a compact `S4a`–`S4e` table near the current approach. The local test after this documentation edit is checking all five links resolve and the files provide a concrete done condition.

Generating patch (193 lines) in , , , , , 


```

```

```

```

```

```

```

```

```

```

```

```
The five guides and the linked plan table are now in place. I’ll run a narrow documentation check to confirm every referenced guide exists and the status-ledger steps are discoverable in `PLAN.md`.

Ran terminal command: rg -o 'docs/steps/STEP4[a-e]_[A-Za-z0-9_]+\.md' PLAN.md | sort -u | while read -r path; do test -f "$path" || exit 1; done && ls docs/steps/STEP4[a-e]_*.md

Created and linked five session-date workflow guides:

- `STEP4a_session_date_inputs.md`
- `STEP4b_session_date_ledger.md`
- `STEP4c_nearby_session_candidates.md`
- `STEP4d_session_status_heatmap.md`
- `STEP4e_session_key_consumers.md`

Made changes.
- [/] S5: Evaluation and review routing — Eligibility-aware S4 evaluation runs; route 18 insufficient-anchor abstentions after the next S4 iteration.

## Active Focus

S4: improve entity anchor coverage on the paragraph axis before character-level snapping.

## Key Intermediate Results & Metrics

- **S1-D1 — HTR under-segmented session-days:** 81.1%
- **S1-D1 — Exact K_f == K_e session-days:** 3.8%
- **S1-D1 — Mean entity containment:** 0.295
- **S1-D1c — Tier-1 Kendall tau:** 0.638; 64.3% of pairs at tau >= 0.8
- **S1-D2 — LLM judge precision:** 60.0% against 53.7% baseline
- **S1-D2b — Opening formula hit rate:** 80.1%
- **S4 — Flat-resolution entity-NW baseline coverage:** 0 / 50 predicted
- **S4 — Paragraph-axis resolved entity coverage:** 480 / 611 paragraphs; 87 unresolved annotation references
- **S5 — Paragraph-axis entity-NW baseline:** coverage 5/21; micro F1 0.576 exact, 0.727 within 2 paragraphs
- **S4 — Opening signal at manual cuts:** 227/360 regex (63.1%); 225/360 S2 top-20 phrases (62.5%)
- **S4 — fuzzy_search opening coverage:** 225/360 (62.5%), unchanged from exact top-20 phrase matching
- **S4 — Held-out opening phrase inventory:** 271 candidates from 3,817 tier-1 flat records; excludes 50 gold dates

## Blockers / Open Questions

No blockers recorded.

## Next Actions

- Implement the S4 paragraph-start entity-sequence baseline for review-code S days.
- Evaluate S4 predictions against boundary gold and report abstention coverage for C and M days.
- Extend successful projections to character-level cut positions after the paragraph-start baseline.

<!-- Manual notes below this line are preserved by scripts/svz.py render. -->

## Notes


## MCP

- mcp_enabled: true
- mcp_server_path: /Users/rikhoekstra/develop/dighum_template/packages/workflow_mcp
- last_mcp_check: 2026-09-01T00:00:00Z

## Dashboard
- docs/dashboard.md
