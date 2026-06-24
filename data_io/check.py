"""CLI: verify tier mounts and print resolved dataset paths."""

from __future__ import annotations

import argparse
import sys

from data_io.manifest import DataManager, TierUnavailableError


def _status_icon(ok: bool) -> str:
    return "ok" if ok else "MISSING"


def run_check(manager: DataManager | None = None) -> int:
    manager = manager or DataManager()
    tier_rows: list[tuple[str, str, str, str]] = []
    for name, tier in sorted(manager.tiers.items()):
        mounted = manager.tier_available(name)
        mount_check = str(tier.mount_check) if tier.mount_check else "-"
        tier_rows.append((name, str(tier.root), mount_check, _status_icon(mounted)))

    dataset_rows: list[tuple[str, str, str, str, str]] = []
    failures = 0
    for name, dataset in sorted(manager.datasets.items()):
        tier_mounted = manager.tier_available(dataset.tier)
        try:
            resolved = manager.resolve(name)
            path_str = str(resolved)
            ok = tier_mounted and resolved.exists()
        except TierUnavailableError:
            path_str = f"<tier {dataset.tier!r} unavailable>"
            ok = False

        if not ok:
            failures += 1
        dataset_rows.append(
            (
                name,
                dataset.tier,
                dataset.phase,
                path_str,
                _status_icon(ok),
            )
        )

    print(f"Manifest: {manager.manifest_path}\n")
    print("Tiers:")
    print(f"{'name':<10} {'root':<45} {'mount_check':<30} status")
    for row in tier_rows:
        print(f"{row[0]:<10} {row[1]:<45} {row[2]:<30} {row[3]}")

    print("\nDatasets:")
    print(f"{'name':<28} {'tier':<10} {'phase':<8} {'path':<55} status")
    for row in dataset_rows:
        print(f"{row[0]:<28} {row[1]:<10} {row[2]:<8} {row[3]:<55} {row[4]}")

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Verify data manifest tiers and dataset paths.")
    parser.parse_args(argv)
    sys.exit(run_check())


if __name__ == "__main__":
    main()
