# Sources

## Used-Car Dataset (`data/raw/used_cars/`)

| File | Make | Rows (approx.) |
|---|---|---|
| audi.csv | Audi | ~10k |
| bmw.csv | BMW | ~11k |
| cclass.csv | Mercedes C-Class | ~3.5k |
| focus.csv | Ford Focus | ~4.5k |
| ford.csv | Ford (all) | ~18k |
| hyundi.csv | Hyundai | ~5k |
| merc.csv | Mercedes | ~14k |
| skoda.csv | Skoda | ~6.5k |
| toyota.csv | Toyota | ~7k |
| vauxhall.csv | Vauxhall | ~13k |
| vw.csv | Volkswagen | ~15k |
| unclean cclass.csv | Mercedes C-Class (raw/unclean) | ~6k |
| unclean focus.csv | Ford Focus (raw/unclean) | ~8k |

## NHTSA vPIC API

- **Endpoint:** `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch`
- **Batch size:** 50 VINs per request _(verify in E2-01)_
- **Rate behaviour:** Subject to automated rate control _(verify in E2-01)_
- **Terms:** Check NHTSA's current terms rather than assuming a license. **Do not redistribute raw API responses.**
- **Verification date:** _TBD — complete as part of task E2-01_
- **Open questions:**
  - Exact error-code vocabulary (needed for E2-04 classifier)
  - Confirmed batch size under current rate rules
  - Standalone vPIC PostgreSQL dump availability

## Data Statement

All event data used in this pipeline is **synthetic**, generated from a seeded random process.
No real vehicle or fleet data is stored in this repository.
