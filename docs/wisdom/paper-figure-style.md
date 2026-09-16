# Paper figure styling

**Status:** stable  
**Applies to:** Republic DH projects with matplotlib figures  
**Portable:** yes

## Rule

Use the **`paper-figures`** add-on (`--addon paper-figures`) instead of copying style cells from notebooks.

```python
from paper_figures import apply_style
style = apply_style()  # reads figure_style.toml
```

Configure presets (`slide` | `paper` | `print`) and palettes in **`figure_style.toml`**.

## Why

`GNB_artikel/paper_figures.ipynb` style was duplicated across notebooks. Centralizing in `paper_figures/` prevents palette drift and keeps Okabe-Ito province colors consistent.

## Do not

- Hardcode province hex colors in plot scripts
- Mix ad-hoc `plt.rcParams` with `apply_style()` in the same session

See add-on: `dighum_template/addons/paper-figures/`
