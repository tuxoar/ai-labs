"""rag CLI — ingest EPUBs, inspect collections, wire Open WebUI.

    uv run rag ingest corpus/*.epub --collection lib-nomic-1000
    uv run rag ingest --manifest corpus/manifest.yaml
    uv run rag status
    uv run rag webui-setup --collection lib-nomic-1000 --read-dsn "$RAG_READ_DSN"
"""

from pathlib import Path

import typer
import yaml

from .chunk import chunk_book
from .config import EMBEDDERS, Settings
from .embed import embed_texts
from .load import collection_stats, existing_hashes, load_chunks
from .parse import parse_epub
from .webui import ensure_connection, ensure_embedding_config, ensure_knowledge

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def ingest(
    epubs: list[Path] = typer.Argument(None, help="EPUB files (or use --manifest)"),
    manifest: Path = typer.Option(None, help="corpus manifest.yaml (books + variants)"),
    collection: str = typer.Option(None, help="target collection name"),
    embedder: list[str] = typer.Option(["embed-nomic"], help="gateway embed model(s)"),
    chunk_size: int = typer.Option(1000),
    chunk_overlap: int = typer.Option(100),
    contextual_headers: bool = typer.Option(False, "--contextual-headers"),
):
    settings = Settings()
    if not settings.gateway_key:
        raise SystemExit("RAG_GATEWAY_KEY not set")
    for m in embedder:
        if m not in EMBEDDERS:
            raise SystemExit(f"unknown embedder {m}; known: {list(EMBEDDERS)}")

    jobs: list[dict] = []
    if manifest:
        spec = yaml.safe_load(manifest.read_text())
        books = [Path(b["path"]) for b in spec["books"]]
        for var in spec["variants"]:
            jobs.append({**{"books": books, "collection": var["collection"]}, **var.get("params", {})})
    else:
        if not epubs or not collection:
            raise SystemExit("either --manifest, or EPUB paths + --collection")
        jobs.append(
            {
                "books": epubs,
                "collection": collection,
                "embedder": embedder,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "contextual_headers": contextual_headers,
            }
        )

    for job in jobs:
        col = job["collection"]
        models = job.get("embedder", embedder)
        for path in job["books"]:
            book = parse_epub(Path(path))
            chunks = chunk_book(
                book,
                col,
                chunk_size=job.get("chunk_size", chunk_size),
                chunk_overlap=job.get("chunk_overlap", chunk_overlap),
                contextual_headers=job.get("contextual_headers", contextual_headers),
            )
            typer.echo(f"[{col}] {book.title!r}: {len(book.chapters)} chapters -> {len(chunks)} chunks")
            # Skip chunks already ingested+embedded BEFORE spending gateway
            # budget — makes re-runs after a mid-corpus failure cheap.
            for m in models:
                done = existing_hashes(settings, col, EMBEDDERS[m][0])
                todo = [c for c in chunks if c.content_hash not in done]
                if not todo:
                    typer.echo(f"[{col}]   {m}: all {len(chunks)} chunks already embedded — skip")
                    continue
                embeddings = {m: embed_texts(settings, m, [c.text for c in todo])}
                stats = load_chunks(settings, book, col, todo, embeddings)
                typer.echo(
                    f"[{col}]   {m}: new={len(todo)} inserted={stats['inserted']} "
                    f"skipped={stats['skipped']} embedded={stats['embedded'][m]}"
                )


@app.command()
def status():
    settings = Settings()
    rows = collection_stats(settings)
    typer.echo(f"{'collection':40} {'chunks':>7} {'nomic':>7} {'bgem3':>7} {'books':>6}")
    for name, chunks, nomic, bgem3, books in rows:
        typer.echo(f"{name:40} {chunks:>7} {nomic:>7} {bgem3:>7} {books:>6}")


@app.command("webui-setup")
def webui_setup(
    collection: list[str] = typer.Option(..., help="collection(s) to expose"),
    read_dsn: str = typer.Option(..., help="postgresql:// DSN for the rag_read role (in-cluster host 'postgres')"),
    embedder: str = typer.Option("embed-nomic"),
):
    settings = Settings()
    if settings.gateway_key:
        ensure_embedding_config(settings, settings.gateway_key, model=embedder)
        typer.echo(f"embedding config: engine=openai model={embedder} (persisted)")
    conn_id = ensure_connection(settings, read_dsn)
    typer.echo(f"external connection: {conn_id}")
    for col in collection:
        result = ensure_knowledge(settings, conn_id, col, embedder)
        typer.echo(f"knowledge {result['name']}: {result['status']} ({result['id']})")


if __name__ == "__main__":
    app()
