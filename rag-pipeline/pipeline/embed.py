"""Embeddings via the LiteLLM gateway with the embed-scoped key — every
vector this pipeline creates is budgeted, rate-limited, and audited like any
other platform call. Batched with backoff for the gateway's RPM/TPM limits."""

import time

import httpx

from .config import Settings


def embed_texts(
    settings: Settings,
    model: str,
    texts: list[str],
    max_retries: int = 6,
) -> list[list[float]]:
    out: list[list[float]] = []
    with httpx.Client(
        base_url=settings.gateway_url,
        headers={"Authorization": f"Bearer {settings.gateway_key}"},
        timeout=120,
    ) as client:
        for start in range(0, len(texts), settings.embed_batch_size):
            batch = texts[start : start + settings.embed_batch_size]
            delay = 2.0
            for attempt in range(max_retries):
                resp = client.post("/embeddings", json={"model": model, "input": batch})
                if resp.status_code == 429:          # budget/RPM backoff
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                out.extend(d["embedding"] for d in data)
                break
            else:
                raise RuntimeError(f"embedding batch failed after {max_retries} retries (429s)")
    return out
