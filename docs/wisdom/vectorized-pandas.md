# Vectorized pandas

**Status:** stable  
**Applies to:** all DH projects  
**Portable:** yes

## Rule

- Prefer vectorized operations: `merge`, `groupby`, `explode`, boolean masks, `.str` accessors.
- Avoid `for row in df.itertuples()` / `iterrows()` for column transforms.
- Avoid `inplace=True` — use explicit assignment (`df = df.drop(...)`).

JSON ingestion may need one list pass to build a frame; everything after that should be vectorized.

## Why

Row loops are slow on 400k+ occurrence tables and hide bugs agents introduce one row at a time.
