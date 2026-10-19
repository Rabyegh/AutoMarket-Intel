"""CLI entry-point for vinpipe."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="vinpipe",
    help="VIN Fleet Enrichment Pipeline — local and Snowflake targets.",
    add_completion=False,
)


@app.command()
def run(
    seed: int = typer.Option(42, help="Random seed for the synthetic generator."),
    batches: int = typer.Option(1, help="Number of synthetic batches to generate."),
    env: str = typer.Option("local", help="Target environment: local | snowflake."),
    fixture_decodes: bool = typer.Option(
        False, "--fixture-decodes", help="Use recorded vPIC fixtures instead of live API."
    ),
    full_refresh: bool = typer.Option(
        False, "--full-refresh", help="Drop and rebuild all models from raw."
    ),
    resume: bool = typer.Option(False, "--resume", help="Resume the last interrupted run."),
) -> None:
    """Run the full pipeline (generate → ingest → enrich → transform)."""
    # TODO: implement pipeline orchestration (E6-03)
    typer.echo(f"[vinpipe] run seed={seed} batches={batches} env={env}")


@app.command()
def sync_s3() -> None:
    """Sync local raw data to S3 (P1)."""
    # TODO: implement S3 sync (E7-01)
    typer.echo("[vinpipe] sync-s3 — not yet implemented")


@app.command()
def load(
    env: str = typer.Option("local", help="Target: local | snowflake.")
) -> None:
    """Load raw parquet into the warehouse."""
    # TODO: implement loader (E1-03 / E7-05)
    typer.echo(f"[vinpipe] load env={env} — not yet implemented")


@app.command()
def parity_check() -> None:
    """Compare DuckDB and Snowflake mart checksums (P1)."""
    # TODO: implement parity check (E7-07)
    typer.echo("[vinpipe] parity-check — not yet implemented")


if __name__ == "__main__":
    app()
