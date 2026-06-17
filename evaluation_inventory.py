from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parent
GROUND_TRUTH = Path(
    "/Users/rikhoekstra/develop/republicgit/ground_truth/tag_de_besluiten/flair_training/flair_training_PER"
)
RC3_PATH = Path(
    "/Users/rikhoekstra/develop/republic_delegates_data/1705_1795/consolidated/"
    "delegates_with_patterns_1705_1795_v1.0_rc3.parquet"
)


@dataclass
class AssetSummary:
    name: str
    path: str
    exists: bool
    task: str
    has_delegate_ids: bool
    shape: str
    recommended_use: str


def _bio_summary(path: Path) -> str:
    sentence_count = 0
    token_count = 0
    per_token_count = 0
    with path.open("r", encoding="utf-8") as handle:
        in_sentence = False
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                if in_sentence:
                    sentence_count += 1
                    in_sentence = False
                continue
            in_sentence = True
            token_count += 1
            parts = line.split()
            if parts and parts[-1].endswith("PER"):
                per_token_count += 1
        if in_sentence:
            sentence_count += 1
    return f"sentences={sentence_count:,}; tokens={token_count:,}; per_tokens={per_token_count:,}"


def _parquet_shape(path: Path) -> str:
    df = pd.read_parquet(path)
    return f"rows={len(df):,}; cols={len(df.columns)}"


def build_inventory() -> list[AssetSummary]:
    assets: list[AssetSummary] = []

    for split in ["validate.txt", "test.txt"]:
        path = GROUND_TRUTH / split
        assets.append(
            AssetSummary(
                name=f"PER BIO {split}",
                path=str(path),
                exists=path.exists(),
                task="span_detection",
                has_delegate_ids=False,
                shape=_bio_summary(path) if path.exists() else "missing",
                recommended_use="Gold standard for exact/overlap PER span extraction.",
            )
        )

    local_assets = [
        (
            "delegates_reference",
            ROOT / "data" / "delegates_reference.parquet",
            "linking_reference",
            True,
            "Reference delegate table for matcher output IDs.",
        ),
        (
            "patterns_reference",
            ROOT / "data" / "patterns_reference.parquet",
            "linking_reference",
            True,
            "Pattern inventory used for variant lookup and candidate generation.",
        ),
        (
            "resolutions_flat",
            ROOT / "resolutions_flat.parquet",
            "production_qa",
            False,
            "Resolution text source for building real KWIC-based adjudication sets.",
        ),
        (
            "rc3_delegate_patterns",
            RC3_PATH,
            "linking_ground_truth",
            True,
            "Best current source for held-out historical variant linking benchmarks.",
        ),
    ]

    for name, path, task, has_delegate_ids, recommended_use in local_assets:
        assets.append(
            AssetSummary(
                name=name,
                path=str(path),
                exists=path.exists(),
                task=task,
                has_delegate_ids=has_delegate_ids,
                shape=_parquet_shape(path) if path.exists() and path.suffix == ".parquet" else "missing",
                recommended_use=recommended_use,
            )
        )

    return assets


def main() -> None:
    assets = build_inventory()
    payload = [asdict(asset) for asset in assets]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()