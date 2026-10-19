"""Integration test stubs — use DuckDB and recorded vPIC fixtures; no network."""
# TODO: implement as part of E5-06
# - Full pipeline run twice: assert identical mart checksums
# - Late-batch scenario: late events land in correct partition, marts update
# - Kill-and-resume: interrupted run completes via --resume with no duplicates
# - Schema-drift fixture: extra/missing vPIC key triggers correct behaviour
# - Unmatched VIN handling: clean + exceptions == distinct input VINs
