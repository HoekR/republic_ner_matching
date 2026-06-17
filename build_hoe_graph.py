"""Build an embedded knowledge graph from HOE classification artifacts.

Inputs
- data/hoe_vocab.parquet      (from hoe_classify.py)
- data/perscatrep.tsv         (canonical/category/reference variants)

Outputs (default: data/hoe_graph)
- nodes.parquet               (node_id, node_type, label, count)
- edges.parquet               (source_id, target_id, edge_type, weight, source)
- node_embedding_index.parquet(row_idx, node_id, node_type, label)
- node_text_embeddings.npz    (scipy sparse matrix)
- vectorizer.pkl              (TfidfVectorizer)
- stats.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import pickle
from dataclasses import dataclass

import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: str
    label: str


def _canon(s: str) -> str:
    return str(s).strip().lower()


def _node_id(node_type: str, label: str) -> str:
    return f"{node_type}:{_canon(label)}"


def build_graph(
    hoe_vocab_path: pathlib.Path,
    perscatrep_path: pathlib.Path,
    out_dir: pathlib.Path,
    min_count: int = 1,
) -> dict[str, int]:
    hoe_df = pd.read_parquet(hoe_vocab_path)
    req_cols = {"normalized_text", "category", "count", "method", "token_set_score"}
    missing = req_cols - set(hoe_df.columns)
    if missing:
        raise ValueError(f"hoe_vocab is missing required columns: {sorted(missing)}")

    hoe_df = hoe_df.copy()
    if "canonical" not in hoe_df.columns:
        # Backward-compatible fallback for older hoe_vocab exports.
        hoe_df["canonical"] = hoe_df["normalized_text"]
    hoe_df = hoe_df[hoe_df["count"] >= min_count]

    pers_df = pd.read_csv(perscatrep_path, sep="\t", dtype=str)
    pers_df = pers_df.dropna(subset=["categorie", "norm_term", "hoedanigheid_in_tag"]).copy()

    nodes: dict[str, Node] = {}
    node_count: dict[str, int] = {}
    edges: list[dict] = []

    def add_node(node_type: str, label: str, count: int = 0) -> str:
        label_n = _canon(label)
        nid = _node_id(node_type, label_n)
        if nid not in nodes:
            nodes[nid] = Node(node_id=nid, node_type=node_type, label=label_n)
            node_count[nid] = 0
        node_count[nid] += int(count)
        return nid

    def add_edge(source_id: str, target_id: str, edge_type: str, weight: float, source: str) -> None:
        edges.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": edge_type,
                "weight": float(weight),
                "source": source,
            }
        )

    # Category and canonical backbone from perscatrep.
    for _, row in pers_df.iterrows():
        cat = _canon(row["categorie"])
        canonical = _canon(row["norm_term"])
        variant = _canon(row["hoedanigheid_in_tag"])

        cat_id = add_node("category", cat)
        can_id = add_node("canonical", canonical)
        var_id = add_node("variant", variant)

        add_edge(can_id, cat_id, "belongs_to_category", 1.0, "perscatrep")
        add_edge(var_id, can_id, "variant_of", 1.0, "perscatrep")

    # Observed variants from hoe_vocab, weighted by frequency.
    for _, row in hoe_df.iterrows():
        var = _canon(row["normalized_text"])
        canonical = _canon(row["canonical"])
        category = _canon(row["category"])
        cnt = int(row["count"])

        var_id = add_node("variant", var, count=cnt)
        can_id = add_node("canonical", canonical, count=cnt)
        cat_id = add_node("category", category, count=cnt)

        add_edge(var_id, can_id, "variant_of", cnt, f"hoe_vocab:{row['method']}")
        add_edge(can_id, cat_id, "belongs_to_category", cnt, "hoe_vocab")

        # Keep fuzzy confidence as a separate edge signal for downstream use.
        if str(row["method"]) == "fuzzy":
            add_edge(var_id, can_id, "fuzzy_support", float(row["token_set_score"]), "hoe_vocab")

    # Build node table.
    nodes_df = pd.DataFrame(
        [
            {
                "node_id": n.node_id,
                "node_type": n.node_type,
                "label": n.label,
                "count": int(node_count.get(n.node_id, 0)),
            }
            for n in nodes.values()
        ]
    ).sort_values(["node_type", "label"]).reset_index(drop=True)

    # Aggregate duplicate edges.
    edges_df = pd.DataFrame(edges)
    edges_df = (
        edges_df.groupby(["source_id", "target_id", "edge_type", "source"], as_index=False)["weight"]
        .sum()
        .sort_values(["edge_type", "weight"], ascending=[True, False])
        .reset_index(drop=True)
    )

    # Embeddings over node labels.
    texts = nodes_df["label"].tolist()
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    mat = vec.fit_transform(texts)

    emb_index_df = nodes_df[["node_id", "node_type", "label"]].copy()
    emb_index_df.insert(0, "row_idx", range(len(emb_index_df)))

    out_dir.mkdir(parents=True, exist_ok=True)
    nodes_df.to_parquet(out_dir / "nodes.parquet", index=False)
    edges_df.to_parquet(out_dir / "edges.parquet", index=False)
    emb_index_df.to_parquet(out_dir / "node_embedding_index.parquet", index=False)
    sparse.save_npz(out_dir / "node_text_embeddings.npz", mat)

    with open(out_dir / "vectorizer.pkl", "wb") as f:
        pickle.dump(vec, f, protocol=5)

    stats = {
        "nodes": int(len(nodes_df)),
        "edges": int(len(edges_df)),
        "categories": int((nodes_df["node_type"] == "category").sum()),
        "canonicals": int((nodes_df["node_type"] == "canonical").sum()),
        "variants": int((nodes_df["node_type"] == "variant").sum()),
        "embedding_rows": int(mat.shape[0]),
        "embedding_dims": int(mat.shape[1]),
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    here = pathlib.Path(__file__).parent
    parser = argparse.ArgumentParser(description="Build embedded HOE knowledge graph artifacts")
    parser.add_argument(
        "--hoe-vocab",
        type=pathlib.Path,
        default=here / "data" / "hoe_vocab.parquet",
        help="Input hoe_vocab parquet",
    )
    parser.add_argument(
        "--perscatrep",
        type=pathlib.Path,
        default=here / "data" / "perscatrep.tsv",
        help="Input perscatrep TSV",
    )
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=here / "data" / "hoe_graph",
        help="Output directory for graph artifacts",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=1,
        help="Minimum observed frequency in hoe_vocab to include variant edges",
    )
    args = parser.parse_args()

    stats = build_graph(
        hoe_vocab_path=args.hoe_vocab,
        perscatrep_path=args.perscatrep,
        out_dir=args.out_dir,
        min_count=args.min_count,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
