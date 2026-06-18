from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import AppSettings, load_settings
from .db import connect_db, init_db as init_database, upsert_city
from .exporter import export_master
from .importer import ImportColumnMapping, import_cities_from_xlsx
from .maintenance import clean_dry_run_data, validate_city_urls
from .metadata import hydrate_city_metadata, hydrate_missing_city_metadata
from .pipeline import RunOptions, process_city
from .priority import apply_priority_cities, load_priority_cities
from .queue import (
    find_city,
    mark_stale as mark_stale_cities,
    reset_city as reset_one_city,
    reset_failed as reset_failed_cities,
    select_failed_cities,
    select_pending_cities,
    select_stale_cities,
)
from .reporting import city_status as get_city_status
from .reporting import overall_status, report as build_report
from .search.serpapi import SerpApiSearchProvider
from .workbook_qa import qa_workbook


app = typer.Typer(help="Discover music, arts, culture, tourism, and calendar source pages by city.")
console = Console()


@app.callback()
def main() -> None:
    """Source discovery only. This tool does not ingest individual events."""


@app.command("init-db")
def init_db(
    database_path: Optional[Path] = typer.Option(None, "--database-path", help="SQLite database path."),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    console.print(f"[green]Initialized database[/green] {settings.database_path}")


@app.command("import-cities")
def import_cities(
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Import XLSX path."),
    database_path: Optional[Path] = typer.Option(None, "--database-path", help="SQLite database path."),
    min_population: Optional[int] = typer.Option(None, "--min-population"),
    max_population: Optional[int] = typer.Option(None, "--max-population"),
    state: Optional[str] = typer.Option(None, "--state"),
    limit: Optional[int] = typer.Option(None, "--limit"),
    priority_only: bool = typer.Option(False, "--priority-only"),
    include_priority_cities: bool = typer.Option(False, "--include-priority-cities"),
    city_column: str = typer.Option("city", "--city-column"),
    state_column: str = typer.Option("state_id", "--state-column"),
    population_column: str = typer.Option("population", "--population-column"),
    lat_column: str = typer.Option("lat", "--lat-column"),
    lng_column: str = typer.Option("lng", "--lng-column"),
) -> None:
    settings = _settings(database_path=database_path, import_file=file)
    init_database(settings.database_path)
    priority_cities = _load_priority_cities(settings)
    with connect_db(settings.database_path) as conn:
        result = import_cities_from_xlsx(
            conn,
            settings.import_xlsx_path,
            column_mapping=ImportColumnMapping(
                city_column=city_column,
                state_column=state_column,
                population_column=population_column,
                lat_column=lat_column,
                lng_column=lng_column,
            ),
            min_population=min_population,
            max_population=max_population,
            state=state,
            limit=limit,
            priority_only=priority_only,
            include_priority_cities=include_priority_cities,
            priority_cities=priority_cities,
        )
        apply_priority_cities(conn, priority_cities)
    table = Table(title="Import Cities")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in result.__dict__.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command("run")
def run(
    limit: Optional[int] = typer.Option(None, "--limit"),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
    export_dir: Optional[Path] = typer.Option(None, "--export-dir"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    min_population: Optional[int] = typer.Option(None, "--min-population"),
    max_population: Optional[int] = typer.Option(None, "--max-population"),
    state: Optional[str] = typer.Option(None, "--state"),
    priority_only: bool = typer.Option(False, "--priority-only"),
    include_priority_cities: bool = typer.Option(False, "--include-priority-cities"),
    refresh_stale_after_days: Optional[int] = typer.Option(None, "--refresh-stale-after-days"),
    max_serpapi_queries_per_city: Optional[int] = typer.Option(None, "--max-serpapi-queries-per-city"),
    max_candidate_domains_per_city: Optional[int] = typer.Option(None, "--max-candidate-domains-per-city"),
    max_total_serpapi_queries: Optional[int] = typer.Option(None, "--max-total-serpapi-queries"),
    stop_if_serpapi_remaining_below: Optional[int] = typer.Option(None, "--stop-if-serpapi-remaining-below"),
    write_city_workbooks: bool = typer.Option(False, "--write-city-workbooks/--no-write-city-workbooks"),
    no_export: bool = typer.Option(False, "--no-export"),
    export_dry_run: bool = typer.Option(False, "--export-dry-run"),
    include_history: bool = typer.Option(False, "--include-history"),
    fail_fast: bool = typer.Option(False, "--fail-fast"),
    force: bool = typer.Option(False, "--force"),
    failed_only: bool = typer.Option(False, "--failed-only"),
    sleep_seconds_between_cities: float = typer.Option(0, "--sleep-seconds-between-cities", min=0),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm live SerpAPI spend estimate."),
) -> None:
    settings = _settings(database_path=database_path, export_dir=export_dir)
    init_database(settings.database_path)
    priority_cities = _load_priority_cities(settings)
    with connect_db(settings.database_path) as conn:
        apply_priority_cities(conn, priority_cities)
        hydrate_missing_city_metadata(conn, settings.import_xlsx_path)
        if failed_only:
            cities = select_failed_cities(
                conn,
                limit,
                min_population=min_population,
                max_population=max_population,
                state=state,
                priority_only=priority_only,
                include_priority_cities=include_priority_cities,
            )
        elif refresh_stale_after_days is not None:
            cities = select_stale_cities(
                conn,
                limit,
                refresh_stale_after_days,
                min_population=min_population,
                max_population=max_population,
                state=state,
                priority_only=priority_only,
                include_priority_cities=include_priority_cities,
            )
        else:
            cities = select_pending_cities(
                conn,
                limit,
                force=force,
                min_population=min_population,
                max_population=max_population,
                state=state,
                priority_only=priority_only,
                include_priority_cities=include_priority_cities,
            )
        if not cities:
            console.print("[yellow]No eligible cities found.[/yellow]")
            return
        _confirm_spend_if_needed(
            cities,
            settings,
            dry_run=dry_run,
            yes=yes,
            max_serpapi_queries_per_city=max_serpapi_queries_per_city,
            stop_if_serpapi_remaining_below=stop_if_serpapi_remaining_below,
        )
        results = []
        options = RunOptions(
            dry_run=dry_run,
            force=force,
            max_serpapi_queries_per_city=max_serpapi_queries_per_city,
            max_candidate_domains_per_city=max_candidate_domains_per_city,
            max_total_serpapi_queries=max_total_serpapi_queries,
            stop_if_serpapi_remaining_below=stop_if_serpapi_remaining_below,
            mode="failed" if failed_only else "refresh" if refresh_stale_after_days else "batch",
        )
        for index, city in enumerate(cities):
            result = process_city(conn, city, settings.config, options)
            results.append(result)
            _print_city_result(city, result)
            if result.status == "failed" and fail_fast:
                raise typer.Exit(1)
            if sleep_seconds_between_cities and index < len(cities) - 1:
                time.sleep(sleep_seconds_between_cities)
        if not no_export:
            if dry_run and not export_dry_run:
                console.print("[yellow]Skipped master export for dry-run data. Pass --export-dry-run to write exports/dry_run/.[/yellow]")
            else:
                output = export_master(
                    conn,
                    settings.export_dir,
                    write_city_workbooks=write_city_workbooks,
                    run_mode="dry_run" if dry_run else "live",
                    include_history=include_history,
                )
                console.print(f"[green]Exported[/green] {output}")


@app.command("run-city")
def run_city(
    city: str = typer.Option(..., "--city"),
    state: Optional[str] = typer.Option(None, "--state"),
    country: str = typer.Option("US", "--country"),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
    export_dir: Optional[Path] = typer.Option(None, "--export-dir"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    max_serpapi_queries_per_city: Optional[int] = typer.Option(None, "--max-serpapi-queries-per-city"),
    max_candidate_domains_per_city: Optional[int] = typer.Option(None, "--max-candidate-domains-per-city"),
    write_city_workbooks: bool = typer.Option(False, "--write-city-workbooks/--no-write-city-workbooks"),
    no_export: bool = typer.Option(False, "--no-export"),
    export_dry_run: bool = typer.Option(False, "--export-dry-run"),
    include_history: bool = typer.Option(False, "--include-history"),
    force: bool = typer.Option(False, "--force"),
    quality_report: bool = typer.Option(False, "--quality-report", help="Print validation/export quality counters after the city run."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    settings = _settings(database_path=database_path, export_dir=export_dir)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        row = find_city(conn, city, state, country)
        if row is None:
            city_id, _ = upsert_city(conn, {"city": city, "state": state, "country": country})
            row = conn.execute("select * from cities where id=?", (city_id,)).fetchone()
        row = hydrate_city_metadata(conn, row["id"], settings.import_xlsx_path)
        _confirm_spend_if_needed(
            [row],
            settings,
            dry_run=dry_run,
            yes=yes,
            max_serpapi_queries_per_city=max_serpapi_queries_per_city,
            stop_if_serpapi_remaining_below=None,
        )
        result = process_city(
            conn,
            row,
            settings.config,
            RunOptions(
                dry_run=dry_run,
                force=force,
                max_serpapi_queries_per_city=max_serpapi_queries_per_city,
                max_candidate_domains_per_city=max_candidate_domains_per_city,
                mode="one-city",
                quality_report=quality_report,
            ),
        )
        _print_city_result(row, result)
        if result.status == "failed":
            raise typer.Exit(1)
        if quality_report:
            _print_quality_report(conn, row["id"])
        if not no_export:
            if dry_run and not export_dry_run:
                console.print("[yellow]Skipped master export for dry-run data. Pass --export-dry-run to write exports/dry_run/.[/yellow]")
            else:
                output = export_master(
                    conn,
                    settings.export_dir,
                    write_city_workbooks=write_city_workbooks,
                    run_mode="dry_run" if dry_run else "live",
                    include_history=include_history,
                )
                console.print(f"[green]Exported[/green] {output}")


@app.command("export")
def export(
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
    export_dir: Optional[Path] = typer.Option(None, "--export-dir"),
    write_city_workbooks: bool = typer.Option(False, "--write-city-workbooks/--no-write-city-workbooks"),
    export_dry_run: bool = typer.Option(False, "--export-dry-run"),
    include_history: bool = typer.Option(False, "--include-history"),
) -> None:
    settings = _settings(database_path=database_path, export_dir=export_dir)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        hydrate_missing_city_metadata(conn, settings.import_xlsx_path)
        output = export_master(
            conn,
            settings.export_dir,
            write_city_workbooks=write_city_workbooks,
            run_mode="dry_run" if export_dry_run else "live",
            include_history=include_history,
        )
    console.print(f"[green]Exported[/green] {output}")


@app.command("qa-workbook")
def qa_workbook_command(
    workbook_path: Optional[Path] = typer.Option(None, "--workbook-path"),
    export_dir: Optional[Path] = typer.Option(None, "--export-dir"),
) -> None:
    settings = _settings(export_dir=export_dir)
    path = workbook_path or settings.export_dir / "master_music_calendar_sources.xlsx"
    issues = qa_workbook(path)
    table = Table(title=f"Workbook QA: {path}")
    table.add_column("Severity")
    table.add_column("Sheet")
    table.add_column("City")
    table.add_column("Issue")
    table.add_column("Source")
    for issue in issues:
        table.add_row(issue.severity, issue.sheet, issue.city, issue.message, issue.source_name or "")
    if not issues:
        table.add_row("ok", "", "", "No workbook QA issues found", "")
    console.print(table)
    if any(issue.severity == "error" for issue in issues):
        raise typer.Exit(1)


@app.command("clean-dry-run-data")
def clean_dry_run(
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        result = clean_dry_run_data(conn)
    table = Table(title="Clean Dry-Run Data")
    table.add_column("Table")
    table.add_column("Rows Removed")
    for key, value in result.__dict__.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command("validate-urls")
def validate_urls(
    city: str = typer.Option(..., "--city"),
    state: Optional[str] = typer.Option(None, "--state"),
    country: str = typer.Option("US", "--country"),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        row = find_city(conn, city, state, country)
        if not row:
            console.print("[yellow]City not found.[/yellow]")
            raise typer.Exit(1)
        result = validate_city_urls(conn, row)
    table = Table(title=f"Validate URLs: {city}, {state or country}")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in result.__dict__.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command("status")
def status(
    city: Optional[str] = typer.Option(None, "--city"),
    state: Optional[str] = typer.Option(None, "--state"),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        if city:
            details = get_city_status(conn, city, state)
            if not details:
                console.print("[yellow]City not found.[/yellow]")
                return
            _print_city_status(details)
        else:
            _print_overall_status(overall_status(conn))


@app.command("report")
def report(
    top: int = typer.Option(50, "--top", min=1),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        data = build_report(conn, top=top)
    for name, rows in data.items():
        table = Table(title=name.replace("_", " ").title())
        if rows:
            for column in rows[0].keys():
                table.add_column(column)
            for row in rows[:top]:
                table.add_row(*(str(value or "") for value in row.values()))
        else:
            table.add_column("status")
            table.add_row("No rows")
        console.print(table)


@app.command("reset-city")
def reset_city(
    city: str = typer.Option(..., "--city"),
    state: Optional[str] = typer.Option(None, "--state"),
    country: str = typer.Option("US", "--country"),
    delete_city_data: bool = typer.Option(False, "--delete-city-data"),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        row = find_city(conn, city, state, country)
        if not row:
            console.print("[yellow]City not found.[/yellow]")
            raise typer.Exit(1)
        reset_one_city(conn, row["id"], delete_city_data=delete_city_data)
    console.print(f"[green]Reset[/green] {city}, {state or country}")


@app.command("reset-failed")
def reset_failed(
    dry_run: bool = typer.Option(False, "--dry-run"),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        count = reset_failed_cities(conn, dry_run=dry_run)
    label = "Would reset" if dry_run else "Reset"
    console.print(f"[green]{label}[/green] {count} failed cities")


@app.command("mark-stale")
def mark_stale(
    older_than_days: int = typer.Option(90, "--older-than-days", min=1),
    database_path: Optional[Path] = typer.Option(None, "--database-path"),
) -> None:
    settings = _settings(database_path=database_path)
    init_database(settings.database_path)
    with connect_db(settings.database_path) as conn:
        count = mark_stale_cities(conn, older_than_days)
    console.print(f"[green]Marked stale[/green] {count} completed cities")


@app.command("serpapi-account")
def serpapi_account() -> None:
    settings = load_settings()
    provider = SerpApiSearchProvider(settings.config.get("serpapi", {}))
    data = provider.account()
    table = Table(title="SerpAPI Account")
    table.add_column("Metric")
    table.add_column("Value")
    mapping = {
        "this_month_usage": data.get("this_month_usage"),
        "monthly_limit": data.get("total_searches_left") or data.get("monthly_limit"),
        "searches_left": data.get("total_searches_left") or data.get("searches_left"),
        "hourly_throughput_limit": data.get("plan_searches_per_hour") or data.get("hourly_throughput_limit"),
    }
    for key, value in mapping.items():
        table.add_row(key, str(value if value is not None else "unknown"))
    console.print(table)


def _settings(
    *,
    database_path: Optional[Path] = None,
    import_file: Optional[Path] = None,
    export_dir: Optional[Path] = None,
) -> AppSettings:
    settings = load_settings()
    if database_path:
        settings.database_path = settings.resolve_path(database_path)
    if import_file:
        settings.import_xlsx_path = settings.resolve_path(import_file)
    if export_dir:
        settings.export_dir = settings.resolve_path(export_dir)
    return settings


def _load_priority_cities(settings: AppSettings) -> dict[tuple[str, str], dict]:
    return load_priority_cities(settings.root_dir / "config" / "priority_cities.yml")


def _confirm_spend_if_needed(
    cities: list[sqlite3.Row],
    settings: AppSettings,
    *,
    dry_run: bool,
    yes: bool,
    max_serpapi_queries_per_city: Optional[int],
    stop_if_serpapi_remaining_below: Optional[int],
) -> None:
    if dry_run:
        return
    per_city = max_serpapi_queries_per_city or settings.config.get("budgets", {}).get("small", {}).get("max_serpapi_queries", 20)
    estimate = len(cities) * int(per_city)
    if stop_if_serpapi_remaining_below is not None:
        account = SerpApiSearchProvider(settings.config.get("serpapi", {})).account()
        remaining = account.get("total_searches_left") or account.get("searches_left")
        if remaining is not None and int(remaining) < stop_if_serpapi_remaining_below:
            console.print(f"[red]SerpAPI searches left ({remaining}) is below threshold.[/red]")
            raise typer.Exit(1)
    if yes:
        console.print(f"[yellow]Estimated worst-case SerpAPI searches: {estimate}[/yellow]")
        return
    if not sys.stdin.isatty():
        console.print("[red]Live SerpAPI run requires --yes in non-interactive mode.[/red]")
        raise typer.Exit(1)
    if not typer.confirm(f"Estimated worst-case SerpAPI searches: {estimate}. Continue?"):
        raise typer.Exit(1)


def _print_city_result(city: sqlite3.Row, result) -> None:
    color = "green" if result.status == "completed" else "red"
    console.print(
        f"[{color}]{city['city']}, {city['state'] or city['country']} {result.status}[/{color}] "
        f"queries={result.queries_completed}/{result.queries_planned} "
        f"candidates={result.candidates_found} verified={result.verified_sources} rejected={result.rejected_sources}"
    )
    if result.error_message:
        console.print(f"[red]{result.error_message}[/red]")


def _print_overall_status(data: dict) -> None:
    table = Table(title="Music Calendar Source Finder Status")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in data.items():
        table.add_row(key, str(value if value is not None else ""))
    console.print(table)


def _print_city_status(details: dict) -> None:
    city = details["city"]
    table = Table(title=f"{city['city']}, {city['state'] or city['country']}")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("status", city["status"])
    table.add_row("candidate_count", str(details["candidate_count"]))
    table.add_row("verified_source_count", str(details["verified_source_count"]))
    table.add_row("rejected_count", str(details["rejected_count"]))
    if details["last_run"]:
        table.add_row("last_run_status", details["last_run"]["status"])
    if details["failure_reason"]:
        table.add_row("failure_reason", details["failure_reason"])
    console.print(table)
    if details["top_sources"]:
        source_table = Table(title="Top Sources")
        source_table.add_column("source_name")
        source_table.add_column("category")
        source_table.add_column("score")
        source_table.add_column("calendar_url")
        for row in details["top_sources"]:
            source_table.add_row(
                str(row.get("source_name") or ""),
                str(row.get("source_category") or ""),
                str(row.get("total_score") or ""),
                str(row.get("best_calendar_url") or ""),
            )
        console.print(source_table)


def _print_quality_report(conn: sqlite3.Connection, city_id: int) -> None:
    rows = conn.execute(
        """
        select coalesce(url_validation_status, 'unvalidated') as url_validation_status, count(*) as count
        from candidate_urls
        where city_id=? and coalesce(run_mode, 'live')='live'
        group by coalesce(url_validation_status, 'unvalidated')
        order by count desc
        """,
        (city_id,),
    ).fetchall()
    table = Table(title="URL Quality Report")
    table.add_column("Validation Status")
    table.add_column("Count")
    for row in rows:
        table.add_row(str(row["url_validation_status"]), str(row["count"]))
    if not rows:
        table.add_row("no live candidates", "0")
    console.print(table)
