"""CLI entry-point for AutoMarket Intel pipeline."""

from __future__ import annotations

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
    import uuid

    from automarket.ingestion.pipeline import run_ingestion
    from automarket.logging_utils import configure

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
    from datetime import date

    import duckdb

    from automarket.simulation.snapshots import SimulationConfig, simulate_snapshots

    typer.secho(
        "WARNING: Simulation output is NOT real market data. "
        "All rows are marked is_simulated=True.",
        fg=typer.colors.YELLOW,
    )

    if not duckdb_path.exists():
        typer.secho("Warehouse not found. Run 'automarket ingest' first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    con = duckdb.connect(str(duckdb_path))
    rows = con.execute("SELECT * FROM raw.raw_used_car_listings").fetchall()
    col_names = [d[0] for d in con.execute("DESCRIBE raw.raw_used_car_listings").fetchall()]
    con.close()

    accepted_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
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

    pd.DataFrame(snapshots)
    con.execute("DROP TABLE IF EXISTS simulated_snapshots")
    con.execute("CREATE TABLE simulated_snapshots AS SELECT * FROM df")
    con.close()

    typer.echo(
        f"Simulation complete: {len(snapshots)} snapshot rows "
        f"({sample_size} listings × {weeks} weeks, seed={seed})"
    )


@app.command(name="upload-s3")
def upload_s3(
    data_dir: Path = typer.Option(
        Path("data/raw/used_cars"),
        help="Directory containing source CSV files.",
        exists=True,
        file_okay=False,
    ),
    run_id: str = typer.Option(
        "",
        help="Pipeline run ID (default: auto-generated UUID prefix).",
    ),
    skip_existing: bool = typer.Option(
        False,
        "--skip-existing",
        help="Skip S3 objects that already exist (idempotent re-run).",
    ),
    no_sources: bool = typer.Option(
        False,
        "--no-sources",
        help="Skip uploading the original source CSV files; upload only normalized Parquet.",
    ),
) -> None:
    """Upload source CSVs and normalized Parquet files to Amazon S3.

    Requires AWS credentials and S3_RAW_BUCKET + AWS_DEFAULT_REGION env vars.
    Use OIDC in CI; use ~/.aws/credentials or env vars for local testing.
    """
    import uuid

    from automarket.ingestion.discovery import discover_files
    from automarket.ingestion.pipeline import read_and_normalize
    from automarket.logging_utils import configure
    from automarket.storage.s3 import S3Config, S3ConfigError, S3UploadError, run_upload

    effective_run_id = run_id.strip() or str(uuid.uuid4())[:8]
    configure(run_id=effective_run_id, step="upload-s3")

    # Validate S3 config before touching any files
    try:
        config = S3Config.from_env()
    except S3ConfigError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    # Discover and process CSV files using existing ingestion logic
    csv_files = discover_files(data_dir)
    if not csv_files:
        typer.secho(f"No ingestible CSV files found in {data_dir}.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.echo(f"Discovered {len(csv_files)} CSV files. Run ID: {effective_run_id}")
    typer.echo(f"Target: s3://{config.bucket}/{config.raw_prefix}/")

    accepted_records: dict[str, list] = {}
    for csv_path in csv_files:
        try:
            accepted, _quarantined = read_and_normalize(csv_path)
            accepted_records[csv_path.stem] = accepted
            typer.echo(f"  {csv_path.name}: {len(accepted)} accepted rows")
        except Exception as exc:
            typer.secho(f"  ERROR reading {csv_path.name}: {exc}", fg=typer.colors.YELLOW)

    if not any(accepted_records.values()):
        typer.secho("No accepted records to upload.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        summary = run_upload(
            config=config,
            data_dir=data_dir,
            run_id=effective_run_id,
            accepted_records=accepted_records,
            upload_sources=not no_sources,
            overwrite=not skip_existing,
        )
    except S3UploadError as exc:
        typer.secho(f"Upload failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    typer.echo(summary.report())
    if not summary.success:
        raise typer.Exit(code=1)


@app.command(name="load-snowflake")
def load_snowflake(
    run_id: str = typer.Argument(
        ...,
        help="Pipeline run ID to load (must match the run_id used in upload-s3).",
    ),
    skip_verify: bool = typer.Option(
        False,
        "--skip-verify",
        help="Skip stage accessibility check and post-load row count verification.",
    ),
) -> None:
    """Load normalized Parquet files from S3 into Snowflake RAW via COPY INTO.

    Prerequisites:
      1. Run 'automarket upload-s3' first to populate the S3 stage.
      2. Snowflake storage integration and external stage must be configured
         (see infra/snowflake/setup.sql and docs/DEPLOY.md).
      3. Set all SNOWFLAKE_* environment variables or CI secrets.

    Idempotency: Snowflake COPY INTO tracks load history per file; the same
    Parquet file at the same S3 key is loaded only once (FORCE=FALSE).
    """
    from automarket.logging_utils import configure
    from automarket.storage.snowflake_loader import (
        SnowflakeConfig,
        SnowflakeConfigError,
        SnowflakeLoadError,
        run_load,
    )

    configure(run_id=run_id, step="load-snowflake")

    try:
        config = SnowflakeConfig.from_env()
    except SnowflakeConfigError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    typer.echo(f"Loading run_id={run_id} into {config.raw_table}")
    typer.echo(f"Stage: {config.stage_name}  Warehouse: {config.warehouse}")

    try:
        result = run_load(config=config, run_id=run_id, verify=not skip_verify)
    except SnowflakeLoadError as exc:
        typer.secho(f"Load failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    typer.echo(result.report())
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
