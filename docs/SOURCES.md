# Data Sources

## UK Used-Car Listing Dataset

**Description:** Static snapshot of UK used-car listings scraped from an automotive listing site.

**Provenance:** Dataset originally published on Kaggle as "100,000 UK Used Car Data Set" by
aditya2803. See: https://www.kaggle.com/datasets/aditya2803/uk-used-car-dataset

> **Note:** The dataset's license should be verified at the Kaggle source before redistribution.
> The repository tracks the CSV files via Git for reproducibility but does not claim ownership.

## What the Dataset Contains

- **Static snapshot** — a single point-in-time export; no listing publication dates
- **Asking prices** — the price the seller is asking; NOT a confirmed sale price
- **UK listings** — all prices in GBP, mileage in miles
- **No VINs** — vehicle identity inferred from make+model+year+fuel_type+transmission+engine_size
- **No location data** — geographic attributes are not present
- **No seller information** — private vs. dealer not indicated

## Files

| File | Make | Rows | Schema | Notes |
|---|---|---|---|---|
| audi.csv | Audi | 10,668 | A | All models |
| bmw.csv | BMW | 10,781 | A | All models |
| ford.csv | Ford | 17,965 | A | All models; 1 row with year=2060 anomaly |
| hyundi.csv | Hyundai | 4,860 | A | Tax column has encoding artefact in header |
| merc.csv | Mercedes-Benz | 13,119 | A | All models |
| skoda.csv | Skoda | 6,267 | A | All models |
| toyota.csv | Toyota | 6,738 | A | All models |
| vauxhall.csv | Vauxhall | 13,632 | A | All models |
| vw.csv | Volkswagen | 15,157 | A | All models |
| cclass.csv | Mercedes-Benz | 3,899 | B | C-Class only; no tax or mpg |
| focus.csv | Ford | 5,454 | B | Focus only; no tax or mpg |
| unclean cclass.csv | — | 4,006 | Excluded | Raw scrape format |
| unclean focus.csv | — | 5,604 | Excluded | Raw scrape format |

## Known Data Quality Issues

1. **ford.csv** — 1 row with `year=2060` (likely a data entry error). Quarantined by validation.
2. **hyundi.csv** — tax column header contains a currency encoding artefact (`tax(£)` corrupted).
   Handled in `discovery.py` column mapping; all 4,860 rows accepted.
3. **cclass.csv, focus.csv** — No `tax` or `mpg` columns. These fields are NULL in the output.
4. **unclean *.csv** — Split columns, GBP-formatted price strings, missing mileage in primary column.
   Excluded from ingestion; retained as raw reference files.
5. **Overlapping coverage** — `cclass.csv` and `merc.csv` both contain C-Class listings.
   `focus.csv` and `ford.csv` both contain Focus listings. Analysts should be aware of
   potential double-counting when combining these sources.
