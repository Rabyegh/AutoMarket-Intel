"""Reconciliation checks and data contract validation."""
# TODO: implement E5-03 and E5-04
# - Reconciliation: raw rows → staged rows → fact rows (dedup count explained)
# - Contract validation: pyarrow schema + value rules; rejects bad batch before partial load
# - Schema drift detector: warns on extra vPIC keys, fails on removal of contracted field
