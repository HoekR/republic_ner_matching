# Notebook generation hygiene

**Status:** stable  
**Applies to:** all DH projects  
**Portable:** yes

## Rule
- Treat committed/agent-touched notebooks (`.ipynb`) as **generated artifacts**.
- Let agents modify notebooks by running a **notebook generator script** (typically `scripts/generate_notebooks.py` using `nbformat`), not by hand-editing JSON.
- Keep interactive experimentation (cell edits, jumping around) as **human-controlled** work in the notebook UI.
- Prefer re-generation after updating the Python template/source over patching `.ipynb` text.

## Why
Hand-editing `.ipynb` JSON is brittle: small formatting/escaping mistakes can break parsing or silently change notebook semantics. Generators are repeatable and keep notebook structure valid.

## Example
In a project, add a generator and then run:

```bash
uv run python scripts/generate_notebooks.py --name inspect_lexicon_csvs
```

and commit the regenerated `.ipynb`.
