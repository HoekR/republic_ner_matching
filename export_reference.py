"""Export delegates_reference.parquet and patterns_reference.parquet.

Reads from the rc3 consolidated parquet and writes two reference files
consumed by match.py:

  delegates_reference.parquet  — one row per delegate
  patterns_reference.parquet   — one row per (delegate, pattern) pair

Usage:
    uv run python export_reference.py [output_dir]

output_dir defaults to data/
"""

import sys
import pathlib
import pandas as pd

RC3_PATH = pathlib.Path(
    "/Users/rikhoekstra/develop/republic_delegates_data"
    "/1705_1795/consolidated"
    "/delegates_with_patterns_1705_1795_v1.0_rc3.parquet"
)

DELEGATES_COLS = [
    "cons_id_str", "fullname", "voornaam", "tussenvoegsel", "geslachtsnaam",
    "heerlijkheid", "provincie", "geboortejaar", "overlijdensjaar",
    "minjaar", "maxjaar", "pattern",
]


def build_delegates(rc3: pd.DataFrame) -> pd.DataFrame:
    """One row per delegate with the simplified pattern string."""
    df = rc3[DELEGATES_COLS].copy()
    df["cons_id_str"] = df["cons_id_str"].astype(str)
    df["pattern"] = df["pattern"].fillna("")
    return df.reset_index(drop=True)


def build_patterns(rc3: pd.DataFrame) -> pd.DataFrame:
    """One row per (delegate, pattern) pair.

    Sources:
    - normalized patterns from the ``pattern`` column (semicolon-separated,
      already lowercased and deduplicated)
    - attested occurrence patterns from the ``patterns`` column (semicolon-
      separated raw occurrence strings from the QA tool)

    Both sets are combined, lowercased, deduplicated per delegate, and output
    with the delegate's year range attached.
    """
    rows = []

    for _, row in rc3.iterrows():
        cid = str(row["cons_id_str"])
        year_min = row["minjaar"]
        year_max = row["maxjaar"]

        seen: set[str] = set()

        # Normalized patterns (already lowercase)
        for p in str(row.get("pattern") or "").split(";"):
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                rows.append({
                    "cons_id_str": cid,
                    "pattern": p,
                    "year_min": year_min,
                    "year_max": year_max,
                })

        # Attested occurrence patterns (lowercase them)
        for p in str(row.get("patterns") or "").split(";"):
            p = p.strip().lower()
            if p and p not in seen:
                seen.add(p)
                rows.append({
                    "cons_id_str": cid,
                    "pattern": p,
                    "year_min": year_min,
                    "year_max": year_max,
                })

    df = pd.DataFrame(rows, columns=["cons_id_str", "pattern", "year_min", "year_max"])
    return df.reset_index(drop=True)


def verify_delegates(df: pd.DataFrame) -> None:
    assert df["cons_id_str"].nunique() == len(df), "cons_id_str not unique"
    assert df["cons_id_str"].notna().all(), "null cons_id_str"
    assert df["pattern"].notna().all(), "null pattern"
    print(f"  delegates_reference: {len(df)} rows — OK")


def verify_patterns(df: pd.DataFrame) -> None:
    assert df["cons_id_str"].notna().all(), "null cons_id_str in patterns"
    assert df["pattern"].notna().all(), "null pattern in patterns"
    n_delegates = df["cons_id_str"].nunique()
    print(f"  patterns_reference:  {len(df)} rows, {n_delegates} delegates — OK")
    # Spot-check: Heinsius should be present
    heinsius = df[df["pattern"].str.contains("heinsius", na=False)]
    assert len(heinsius) > 0, "heinsius not found in patterns"
    print(f"  spot-check: 'heinsius' found in {len(heinsius)} pattern row(s) — OK")


def main(out_dir: str = "data") -> None:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Reading rc3 from {RC3_PATH} ...")
    rc3 = pd.read_parquet(RC3_PATH)
    print(f"  rc3: {rc3.shape[0]} rows, {rc3.shape[1]} columns")

    print("Building delegates_reference ...")
    delegates = build_delegates(rc3)
    del_path = out / "delegates_reference.parquet"
    delegates.to_parquet(del_path, index=False)
    verify_delegates(delegates)

    print("Building patterns_reference ...")
    patterns = build_patterns(rc3)
    pat_path = out / "patterns_reference.parquet"
    patterns.to_parquet(pat_path, index=False)
    verify_patterns(patterns)

    print(f"\nExported to {out}/")
    print(f"  {del_path.name}")
    print(f"  {pat_path.name}")


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    main(out_dir)
