# Orphan remotes — decisions (2026-09-28)

| Local path | Decision | Remote |
|------------|----------|--------|
| `gnb_analysis` | Keep separate (RPP analytics). Do not merge into NER. | https://github.com/HoekR/gnb_analysis |
| `republic_resolutions_early` | Keep separate (pre-1626 segmentation). | https://github.com/HoekR/republic_resolutions_early |
| `republic_attendance_1630` | Keep separate; implements `gnb_analysis` PLAN_1630_1704. | https://github.com/HoekR/republic_attendance_1630 |

**Do not push to `HuygensING/republic-project`.** That remote on `republicgit` is for fetch/sync of upstream only.

Personal `HoekR/*` remotes above were created empty via `gh repo create`; **initial push is deferred** until you explicitly ask. Delete those GitHub repos if you prefer local-only.

See [REPUBLIC_REPO_INVENTORY.md](REPUBLIC_REPO_INVENTORY.md).
