import argparse
import csv
import json
from pathlib import Path

import pandas as pd
from republic_corpus import SessionsArchive

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path('/Volumes/2tb disk/datasets/republic')
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

_sessions_archive = SessionsArchive()


def read_session_texts(session_ids: list[str]) -> dict[str, str]:
    """Read source text for the given session IDs via SessionsArchive."""
    results: dict[str, str] = {}
    for sid in session_ids:
        try:
            payload = _sessions_archive.read_session(sid)
            lines = [
                line.get('text', '').strip()
                for region in payload.get('text_regions', [])
                for line in region.get('lines', [])
                if line.get('text', '').strip()
            ]
            results[sid] = ' '.join(lines)
        except (KeyError, Exception):
            results[sid] = ''
    return results


def load_person_name_map(path: Path) -> dict:
    result = {}
    with path.open(encoding='utf-8') as f:
        for row in csv.DictReader(f):
            pid = row.get('id', '').strip()
            name = row.get('name', '').strip()
            if pid:
                result[pid] = name
    return result


def load_annotations(path: Path) -> pd.DataFrame:
    items = json.loads(path.read_text())
    rows = []
    for item in items:
        reference = item.get("reference", {})
        rows.append({
            "entity": item.get("entity"),
            "resolution_id": reference.get("resolution_id"),
            "tag_text": reference.get("tag_text"),
        })
    return pd.DataFrame(rows)


def resolve_enriched_entities(df_res: pd.DataFrame, person_map: dict) -> pd.DataFrame:
    enriched = df_res[["date", "places", "persons", "institutions", "text"]].copy()
    enriched["resolution_id"] = enriched.index
    enriched["place_names"] = enriched["places"].apply(lambda vals: [str(v) for v in vals if v])
    enriched["person_names"] = enriched["persons"].apply(
        lambda vals: [person_map.get(str(v), str(v)) for v in vals if v]
    )
    enriched["org_names"] = enriched["institutions"].apply(lambda vals: [str(v) for v in vals if v])
    enriched["date_str"] = enriched["date"].astype(str)
    return enriched[["resolution_id", "date", "date_str", "place_names", "person_names", "org_names", "text"]]


def resolve_flat_entities(df_flat, loc_ann, per_ann, org_ann):
    def aggregate_tags(ann_df):
        if ann_df.empty:
            return pd.Series(dtype=object)
        return ann_df.dropna(subset=["tag_text"]).groupby("resolution_id")["tag_text"].apply(
            lambda s: list(s.unique())
        )

    loc_groups = aggregate_tags(loc_ann)
    per_groups = aggregate_tags(per_ann)
    org_groups = aggregate_tags(org_ann)

    flat = df_flat[["id", "date", "resolutions_text", "paragraph_texts"]].copy()
    flat = flat.rename(columns={"id": "resolution_id"})
    flat["date_str"] = flat["date"].astype(str)
    flat["place_names"] = flat["resolution_id"].map(loc_groups).apply(lambda v: v if isinstance(v, list) else [])
    flat["person_names"] = flat["resolution_id"].map(per_groups).apply(lambda v: v if isinstance(v, list) else [])
    flat["org_names"] = flat["resolution_id"].map(org_groups).apply(lambda v: v if isinstance(v, list) else [])
    return flat[["resolution_id", "date", "date_str", "place_names", "person_names", "org_names", "resolutions_text", "paragraph_texts"]]


def build_sessions_sheet(date_str: str, df_flat_full: pd.DataFrame, loc_ann, per_ann, org_ann) -> pd.DataFrame:
    """Session-level view: one row per session for the given date."""
    session_index = pd.read_parquet(DATA_DIR / "index/session_index_all.parquet")
    sessions_day = session_index[session_index["session_date"] == date_str].copy()

    # Extract session_id from flat resolution ids (e.g. session-3788-num-1-resolution-1 -> session-3788-num-1)
    flat = df_flat_full.copy()
    flat["session_id"] = flat["id"].str.extract(r"^(session-\d+-num-\d+)")
    flat_day = flat[flat["date"].astype(str) == date_str]

    resolution_counts = flat_day.groupby("session_id")["id"].apply(list).rename("resolution_ids")
    sessions_day = sessions_day.merge(resolution_counts, on="session_id", how="left")
    sessions_day["n_resolutions"] = sessions_day["resolution_ids"].apply(
        lambda v: len(v) if isinstance(v, list) else 0
    )

    # Aggregate annotation entities per session via resolution_ids
    def agg_entities_for_session(resolution_ids, ann_df):
        if not isinstance(resolution_ids, list) or ann_df.empty:
            return []
        mask = ann_df["resolution_id"].isin(resolution_ids)
        tags = ann_df.loc[mask, "tag_text"].dropna().unique().tolist()
        return tags

    sessions_day["place_names"] = sessions_day["resolution_ids"].apply(
        lambda ids: agg_entities_for_session(ids, loc_ann)
    )
    sessions_day["person_names"] = sessions_day["resolution_ids"].apply(
        lambda ids: agg_entities_for_session(ids, per_ann)
    )
    sessions_day["org_names"] = sessions_day["resolution_ids"].apply(
        lambda ids: agg_entities_for_session(ids, org_ann)
    )

    # Aggregate resolution texts per session
    session_texts = (
        flat_day.groupby("session_id")["resolutions_text"]
        .apply(lambda s: "\n\n".join(s.dropna().astype(str)))
        .rename("resolutions_text")
    )
    sessions_day = sessions_day.merge(session_texts, on="session_id", how="left")

    sessions_day["resolution_ids"] = sessions_day["resolution_ids"].apply(
        lambda v: "; ".join(v) if isinstance(v, list) else ""
    )

    # Read source text via SessionsArchive
    print("  Reading session text via SessionsArchive...")
    session_ids = sessions_day["session_id"].dropna().tolist()
    session_texts = read_session_texts(session_ids)
    sessions_day["session_text"] = sessions_day["session_id"].map(session_texts)

    cols = ["session_id", "session_date", "session_num", "inventory_num",
            "resolution_type", "session_weekday", "n_resolutions",
            "resolution_ids", "session_text", "place_names", "person_names", "org_names"]
    return sessions_day[cols].reset_index(drop=True)


def build_combined_sheet(enriched, flat):
    e = enriched.copy()
    e["source"] = "enriched"
    e = e.rename(columns={"text": "source_text"})
    e = e[["source", "resolution_id", "date", "date_str", "place_names", "person_names", "org_names", "source_text"]]

    f = flat.copy()
    f["source"] = "flat"
    f = f.rename(columns={"resolutions_text": "source_text"})
    f = f[["source", "resolution_id", "date", "date_str", "place_names", "person_names", "org_names", "source_text"]]

    return pd.concat([e, f], ignore_index=True)


def _stringify_lists(df):
    for col in df.columns:
        if df[col].apply(lambda v: isinstance(v, list)).any():
            df[col] = df[col].apply(lambda v: "; ".join(v) if isinstance(v, list) else v)
    return df


def main(date_str: str):
    print("Loading enriched resolutions...")
    df_res = pd.read_json(DATA_DIR / "derived/enriched_resolutions_1626_1630_complete.json")

    print("Loading flat resolutions...")
    df_res_flat = pd.read_parquet(DATA_DIR / "resolutions/resolutions_flat.parquet")

    print("Loading person name map...")
    person_map = load_person_name_map(DATA_DIR / "gnb/persons_id_name.csv")

    enriched = resolve_enriched_entities(df_res, person_map)

    print("Loading LOC annotations...")
    loc_ann = load_annotations(DATA_DIR / "annotations/LOC-annotations.json")
    print("Loading PER annotations...")
    per_ann = load_annotations(DATA_DIR / "annotations/PER-annotations.json")
    print("Loading ORG annotations...")
    org_ann = load_annotations(DATA_DIR / "annotations/ORG-annotations.json")

    flat = resolve_flat_entities(df_res_flat, loc_ann, per_ann, org_ann)

    print("Building sessions sheet...")
    sessions_sheet = _stringify_lists(
        build_sessions_sheet(date_str, df_res_flat, loc_ann, per_ann, org_ann)
    )

    enriched_date = _stringify_lists(enriched[enriched["date_str"] == date_str].copy())
    flat_date = _stringify_lists(flat[flat["date_str"] == date_str].copy())
    combined = _stringify_lists(build_combined_sheet(
        enriched[enriched["date_str"] == date_str].copy(),
        flat[flat["date_str"] == date_str].copy(),
    ))

    print(f"  sessions: {len(sessions_sheet)}, enriched rows: {len(enriched_date)}, flat rows: {len(flat_date)}, combined rows: {len(combined)}")

    output_file = OUTPUT_DIR / f"resolution_entities_{date_str}.xlsx"
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        sessions_sheet.to_excel(writer, sheet_name="sessions", index=False)
        enriched_date.to_excel(writer, sheet_name="enriched", index=False)
        flat_date.to_excel(writer, sheet_name="flat", index=False)
        combined.to_excel(writer, sheet_name="combined", index=False)

    print(f"Wrote: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export date-based resolution entity sheets.")
    parser.add_argument("date", help="Date to export in YYYY-MM-DD format")
    args = parser.parse_args()
    main(args.date)
