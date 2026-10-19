"""vPIC API client, response parser, and decode-status classifier."""
# TODO: implement E2-03 and E2-04
# - Client: chunk by 50, polite pacing, User-Agent, exponential backoff w/ jitter, per-chunk checkpoint
# - Parser: flatten JSON to typed rows; status classifier (error codes → status classes)
# - Field names MUST be verified against live API response (see E2-01 / docs/SOURCES.md)
