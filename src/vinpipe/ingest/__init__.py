"""Raw landing writer and idempotent DuckDB loader."""
# TODO: implement E1-02 and E1-03
# - Landing writer: batch dir, manifest (row count, SHA-256, schema, seed), deterministic batch_id
# - Idempotent loader: skip if manifest hash already loaded, else delete-by-batch + insert in one tx
