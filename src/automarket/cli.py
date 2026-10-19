"""CLI entry-point for AutoMarket Intel pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="automarket",
    help="AutoMarket Intel — Used-Car Pricing & Inventory Intelligence Platform.",
    add_completion=False,
)


@app.command()
def ingest(
    data_dir: Path = typer.Option(
        Path("data/raw/used_cars"),
        help="Directory containing used-car CSV files.",
        exists=True,
        file_okay=False,
    ),
    duckdb_path: Path = typer.Option(
        Path("data/warehouse.duckdb"),
        help="Path to DuckDB database file.",
    ),
    full_refresh: bool = typer.Option(
        False,
        "--full-refresh",
        help="Drop and recreate raw tables before loading.",
    ),
) -> None:
    """Ingest CSV listing files into DuckDB (raw layer)."""
    from automarket.ingestion.pipeline import run_ingestion
    from automarket.logging_utils import configure
    import uuid

    run_id = str(uuid.uuid4())[:8]
    configure(run_id=run_id, step="ingest")

    stats = run_ingestion(
        data_dir=data_dir,
        duckdb_path=duckdb_path,
        full_refresh=full_refresh,
    )
    typer.echo(stats.report())

    if stats.rows_accepted == 0:
        typer.secho("ERROR: No rows were accepted. Check input files.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def report(
    duckdb_path: Path = typer.Option(
        Path("data/warehouse.duckdb"),
        help="Path to DuckDB database file.",
    ),
) -> None:
    """Print a quick analytical summary from the mart tables."""
    import duckdb

    if not duckdb_path.exists():
        typer.secho(
            f"Warehouse not found at {duckdb_path}. Run 'automarket ingest' first.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    con = duckdb.connect(str(duckdb_path), read_only=True)

    typer.echo("\n=== Inventory by Make ===")
    try:
        rows = con.execute("""
            SELECT make, COUNT(*) AS listings, ROUND(AVG(price_gbp)) AS avg_price_gbp,
                   MIN(price_gbp) AS min_price, MAX(price_gbp) AS max_price
            FROM raw.raw_used_car_listings
            GROUP BY make
            ORDER BY listings DESC
        """).fetchall()
        typer.echo(f"{'Make':<20} {'Listings':>9} {'Avg £':>9} {'Min £':>8} {'Max £':>8}")
        typer.echo("-" * 58)
        for row in rows:
            typer.echo(f"{row[0]:<20} {row[1]:>9} {row[2]:>9} {row[3]:>8} {row[4]:>8}")
    except Exception as e:
        typer.secho(f"Could not read mart data: {e}", fg=typer.colors.YELLOW)

    typer.echo("\n=== Fuel Type Distribution ===")
    try:
        rows = con.execute("""
            SELECT fuel_type, COUNT(*) AS listings,
                   ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
            FROM raw.raw_used_car_listings
            GROUP BY fuel_type
            ORDER BY listings DESC
        """).fetchall()
        for row in rows:
            typer.echo(f"  {row[0]:<12} {row[1]:>7} listings ({row[2]}%)")
    except Exception as e:
        typer.secho(f"Could not read fuel data: {e}", fg=typer.colors.YELLOW)

    typer.echo("\n=== Quarantine Summary ===")
    try:
        count = con.execute("SELECT COUNT(*) FROM raw.raw_quarantine").fetchone()[0]
        typer.echo(f"  Quarantined records: {count}")
        if count > 0:
            rows = con.execute("""
                SELECT rejection_reason, COUNT(*) AS n
                FROM raw.raw_quarantine
                GROUP BY rejection_reason
                ORDER BY n DESC
                LIMIT 5
            """).fetchall()
            for row in rows:
                typer.echo(f"    {row[1]:>6}  {row[0]}")
    except Exception as e:
        typer.secho(f"Could not read quarantine: {e}", fg=typer.colors.YELLOW)

    con.close()


@app.command()
def simulate(
    duckdb_path: Path = typer.Option(
        Path("data/warehouse.duckdb"),
        help="Path to DuckDB database file.",
    ),
    seed: int = typer.Option(42, help="Random seed for reproducibility."),
    weeks: int = typer.Option(8, help="Number of weekly observation snapshots."),
    sample_size: int = typer.Option(1000, help="Number of listings to simulate."),
) -> None:
    """Generate simulated listing snapshots (OPTIONAL — not real market data)."""
    import duckdb
    from automarket.simulation.snapshots import SimulationConfig, simulate_snapshots
    from datetime import date

    typer.secho(
        "WARNING: Simulation output is NOT real market data. "
        "All rows are marked is_simulated=True.",
        fg=typer.colors.YELLOW,
    )

    if not duckdb_path.exists():
        typer.secho(
            "Warehouse not found. Run 'automarket ingest' first.", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    con = duckdb.connect(str(duckdb_path))
    rows = con.execute("SELECT * FROM raw.raw_used_car_listings").fetchall()
    col_names = [d[0] for d in con.execute("DESCRIBE raw.raw_used_car_listings").fetchall()]
    con.close()

    accepted_rows = [dict(zip(col_names, r)) for r in rows]
    config = SimulationConfig(
        seed=seed,
        start_date=date(2023, 1, 1),
        weeks=weeks,
        sample_size=sample_size,
    )

    snapshots = simulate_snapshots(accepted_rows, config)

    # Load into DuckDB
    con = duckdb.connect(str(duckdb_path))
    con.execute("DROP TABLE IF EXISTS simulated_snapshots")
    con.execute("""
        CREATE TABLE simulated_snapshots AS
        SELECT * FROM (VALUES (NULL)) t(x) WHERE FALSE
    """)
    # Build from dataframe-style insert
    import pandas as pd
    df = pd.DataFrame(snapshots)
    con.execute("DROP TABLE IF EXISTS simulated_snapshots")
    con.execute("CREATE TABLE simulated_snapshots AS SELECT * FROM df")
    con.close()

    typer.echo(
        f"Simulation complete: {len(snapshots)} snapshot rows "
        f"({sample_size} listings × {weeks} weeks, seed={seed})"
    )


if __name__ == "__main__":
    app()
