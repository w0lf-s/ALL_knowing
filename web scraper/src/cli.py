from __future__ import annotations

import asyncio
import json

import typer

from src.pipeline import run_pipeline


def main(
    query: str = typer.Argument(..., help="Company name"),
    summary: bool = typer.Option(False, "--summary", help="Print sources_status summary only"),
    no_groq: bool = typer.Option(False, "--no-groq"),
    no_playwright: bool = typer.Option(False, "--no-playwright"),
) -> None:
    dossier = asyncio.run(
        run_pipeline(query, use_groq=not no_groq, use_playwright=not no_playwright)
    )
    if summary:
        out = {
            "query": dossier.query,
            "resolved": dossier.resolved.model_dump(),
            "sources_status": dossier.sources_status.model_dump(),
            "meta": dossier.meta.model_dump(),
            "counts": {
                "filings": len(dossier.filings),
                "news": len(dossier.news.articles),
                "press": len(dossier.press),
                "github_repos": len(dossier.github.repos),
            },
        }
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    typer.echo(json.dumps(dossier.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    typer.run(main)
