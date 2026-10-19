"""Generate reproducible simulated observation snapshots from the static dataset.

IMPORTANT LIMITATIONS:
- Source data is a static snapshot; it contains no real listing timestamps.
- Simulated observation_date values are INVENTED, not real publication dates.
- Simulated price drift is a random walk, not observed market behaviour.
- A row with is_active=False does NOT confirm a sale or any real market event.
- Every row produced here has is_simulated=True. Do not mix with raw source rows.

This module is useful for:
- Demonstrating how the pipeline would handle repeated observations.
- Testing incremental dbt models with snapshot-style data.
- Portfolio demonstration of time-series capability.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

# Number of weekly observations to simulate
DEFAULT_WEEKS = 8

# Probability that a listing survives each week (inventory aging)
SURVIVAL_RATE = 0.85

# Maximum weekly asking-price drift as a fraction of current price
PRICE_DRIFT_FRACTION = 0.03


@dataclass
class SimulationConfig:
    """Configuration for the historical simulation."""

    seed: int = 42
    start_date: date = date(2023, 1, 1)
    weeks: int = DEFAULT_WEEKS
    survival_rate: float = SURVIVAL_RATE
    price_drift_fraction: float = PRICE_DRIFT_FRACTION
    sample_size: int | None = None  # None = use all accepted rows


def simulate_snapshots(
    accepted_rows: list[dict[str, Any]],
    config: SimulationConfig | None = None,
) -> list[dict[str, Any]]:
    """Generate weekly listing snapshots from a list of accepted source rows.

    Returns a list of snapshot rows. Each row includes:
        - All original fields from the source row
        - observation_date: the simulated observation week start (YYYY-MM-DD)
        - simulated_price_gbp: the asking price for that observation
        - is_active: whether the listing appears in that week's snapshot
        - is_simulated: always True — NEVER treat these as real observations
        - simulation_seed: the seed used, for reproducibility

    Args:
        accepted_rows: normalised accepted rows from the ingestion pipeline
        config: simulation parameters; uses defaults if None

    Returns:
        list of snapshot dicts, sorted by observation_date then source_file
    """
    cfg = config or SimulationConfig()
    rng = random.Random(cfg.seed)

    source = accepted_rows
    if cfg.sample_size is not None:
        source = rng.sample(source, min(cfg.sample_size, len(source)))

    snapshots: list[dict[str, Any]] = []

    for row in source:
        current_price = row.get("price_gbp") or 0
        is_active = True

        for week_offset in range(cfg.weeks):
            obs_date = cfg.start_date + timedelta(weeks=week_offset)

            # Determine if listing survives this week
            if week_offset > 0:
                is_active = is_active and (rng.random() < cfg.survival_rate)

            # Small random price drift (up or down)
            drift = rng.uniform(-cfg.price_drift_fraction, cfg.price_drift_fraction)
            current_price = max(100, round(current_price * (1 + drift)))

            snapshots.append({
                **row,
                "observation_date": obs_date.isoformat(),
                "simulated_price_gbp": current_price,
                "is_active": is_active,
                "is_simulated": True,
                "simulation_seed": cfg.seed,
            })

    return sorted(snapshots, key=lambda r: (r["observation_date"], r["source_file"]))
