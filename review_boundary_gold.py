import pandas as pd

from data_io import load, resolve


SAMPLE_DATASET = "boundary_gold_sample"
REVIEW_DATASET = "boundary_gold_exception_review"
REVIEW_CODE_MAP = {
    "segmentable": "S",
    "cross_day_shift": "C",
    "missing_in_htr": "M",
    "missing in htr": "M",
    "nihil_actum": "N",
    "uncertain": "?",
}


def transition_count(day: dict) -> int:
    return sum(
        boundary.get("kind") in {"cut", "start"}
        for boundary in day.get("boundaries", [])
    )


def prior_reviews() -> pd.DataFrame:
    path = resolve(REVIEW_DATASET)
    if not path.exists():
        return pd.DataFrame(columns=["date", "review_code", "unavailable_enriched_count", "note"])
    existing = load(REVIEW_DATASET).copy()
    if "review_code" not in existing and "review_status" in existing:
        existing["review_code"] = existing["review_status"].map(REVIEW_CODE_MAP).fillna("")
    return existing.reindex(columns=["date", "review_code", "unavailable_enriched_count", "note"])


def main() -> None:
    sample = load(SAMPLE_DATASET)
    review = pd.DataFrame(
        {
            "date": day["date"],
            "k_e": day["k_e"],
            "k_f": day["k_f"],
            "stratum": day["stratum"],
            "expected_transitions": day["k_e"] - 1,
            "observed_transitions": transition_count(day),
            "starts_mid_resolution": day.get("starts_mid_resolution", False),
            "trailing_end_marker": any(
                boundary.get("kind") == "end_of_last_resolution"
                for boundary in day.get("boundaries", [])
            ),
        }
        for day in sample["days"]
    )
    exceptions = review.query("observed_transitions != expected_transitions")
    exceptions = exceptions.merge(prior_reviews(), on="date", how="left")
    exceptions[["review_code", "note"]] = exceptions[["review_code", "note"]].fillna("")
    exceptions.to_csv(resolve(REVIEW_DATASET), index=False)
    print(f"Wrote {len(exceptions)} exception day(s) to {resolve(REVIEW_DATASET)}")


if __name__ == "__main__":
    main()