# Pandas dates before 1678

**Status:** stable  
**Applies to:** all DH projects (early modern corpus)  
**Portable:** yes

## Rule

Never use `datetime`, `Timestamp`, or `pd.to_datetime()` for calendar dates before **1678**.

Use **`pd.Period` / `pd.PeriodIndex` with `freq="D"`** for resolution dating, window checks, and day-level joins.

## Why

Pandas datetime epoch starts at 1678-01-01. Earlier dates raise `OutOfBoundsDatetime` or silently misbehave in edge cases.

## Example

```python
# Wrong
df["date"] = pd.to_datetime(df["d"].astype(str) + "-" + df["m"].astype(str) + "-" + df["j"].astype(str))

# Right
df["date"] = pd.PeriodIndex.from_fields(year=df["j"], month=df["m"], day=df["d"], freq="D")
```

Compare periods via ordinal arithmetic:

```python
(df["date"] - anchor).astype(int).abs()
```

Filter malformed ISO strings with vectorized month/day checks **before** constructing `PeriodIndex`.
