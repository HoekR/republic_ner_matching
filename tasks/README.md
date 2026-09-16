# Task Workspaces

Use one folder per large project step when the work benefits from its own overview notebook,
intermediate outputs, and validation notes.

Suggested pattern:

```text
tasks/
  S0_example/
    00_task_overview.ipynb
    scripts/
    data/
```

Keep heavy, reproducible work in Python scripts. Use the overview notebook to inspect outputs,
plot metrics, and capture interpretation.
