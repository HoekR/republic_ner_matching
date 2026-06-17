# Evaluation Plan

This plan separates three questions that should not be tuned together:

1. Did we extract the correct person span?
2. Did we link that span to the correct delegate?
3. Does the end-to-end workflow behave well on real KWIC records, including short context and multi-name spans?

## Milestone 1 - Asset Inventory

Goal:
- Freeze which datasets answer which evaluation question.

Outputs:
- Machine-readable inventory from `evaluation_inventory.py`
- Short asset table with task coverage and current readiness

Success criteria:
- Every evaluation asset is assigned one primary use
- Missing files are surfaced explicitly
- We can point to one preferred dataset for span detection, one for linking, and one for production QA

## Milestone 2 - Span Benchmark

Goal:
- Evaluate mention extraction against token-level PER annotations.

Primary source:
- `ground_truth/tag_de_besluiten/flair_training/flair_training_PER/{validate,test}.txt`

Outputs:
- BIO-to-span parser
- Span table with source id, gold span text, predicted span text, exact match, overlap match
- Metrics: precision, recall, F1 for exact and relaxed overlap

Success criteria:
- We can distinguish extraction errors from downstream linking errors

## Milestone 3 - Linking Benchmark

Goal:
- Evaluate whether extracted spans resolve to the correct `cons_id_str`.

Primary source:
- Held-out labeled benchmark from `extending_matching.ipynb` (`benchmark_source`, `benchmark_split`, `test_real`)

Outputs:
- Stable materialization step for `test_real`
- Metrics: top-1 accuracy, top-3 recall, top-5 recall, score-gap calibration
- Error slices by divergence band

Success criteria:
- We have one repeatable identity-resolution benchmark with delegate IDs

## Milestone 4 - Hard Cases

Goal:
- Evaluate difficult structures separately instead of hiding them inside overall metrics.

Priority slices:
- short KWIC
- multi-name span
- collective/group span
- non-name false positive

Outputs:
- Span-type rules
- Abstain policy for short or ambiguous context
- Slice-level metrics and failure tables

Success criteria:
- Hard cases have explicit handling and dedicated measurements

## Milestone 5 - Adjudicated Production Set

Goal:
- Build a small real-resolution evaluation set that reflects notebook usage.

Primary source:
- Sampled KWIC records from `resolution_searching.ipynb`

Outputs:
- Manual review table with `kwic_id`, contexts, gold span type, gold `cons_id_str`, notes
- Stratified sample across short, long, single, multiple, and title-heavy cases

Success criteria:
- We have a compact production-faithful acceptance set for iteration

## Milestone 6 - Unified Runner

Goal:
- Make all evaluation tracks runnable with one command.

Outputs:
- Single runner script or notebook entry point
- Summary tables for span, linking, and production QA
- Failure exports for manual review

Success criteria:
- Matcher changes can be assessed against all benchmarks without ad hoc notebook work

## Execution Order

1. Milestone 1: asset inventory
2. Milestone 3: linking benchmark, because labeled delegate IDs already exist
3. Milestone 2: span benchmark
4. Milestone 4: hard-case handling and abstention
5. Milestone 5: adjudicated production set
6. Milestone 6: unified runner

## Notes

- The external PER BIO files are best for span detection, not identity linking.
- The `test_real` benchmark is the current best source for delegate-ID evaluation.
- The adjudicated KWIC set is required before tuning aggressively for short context and multi-name spans.