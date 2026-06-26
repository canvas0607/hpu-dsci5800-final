"""Smoke test for the image-generation model.

Mirrors test_openai.py but exercises the images endpoint: it calls the
configured image model and saves the returned image to disk so the result can
be inspected. Run with `uv run python test_images.py`.
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError
from openai.types import Image

load_dotenv()

OUTPUT_DIR = Path(os.getenv("IMAGE_OUTPUT_DIR", "results"))

PROMPT = (
    "Generate an original interior design concept image, not a brand product photo. "
    "No logos, no text, no watermark, no catalog layout. "
    "Style: realistic cozy home interior, warm natural light, clean composition, practical scale."
)


def resolve_base_url() -> str:
    """Return an OpenAI-style base URL (.../v1) for the images client.

    OPENAI_IMAGES_URL often points straight at the endpoint
    (``.../v1/images/generations``). The SDK appends ``/images/generations``
    itself, so the value must be trimmed back to the ``/v1`` base or every
    request 404s.
    """
    url = (os.getenv("OPENAI_IMAGES_URL") or os.getenv("OPENAI_URL", "http://127.0.0.1:15721/v1")).rstrip("/")
    suffix = "/images/generations"
    if url.endswith(suffix):
        url = url[: -len(suffix)]
    return url


async def save_image(image: Image, output_dir: Path) -> Path:
    """Persist one image result (b64 or url) to disk and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"test-image-{stamp}.png"

    b64 = image.b64_json
    if b64:
        path.write_bytes(base64.b64decode(b64))
        return path

    url = image.url
    if url:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        return path

    raise ValueError("image response contained neither b64_json nor url")


async def main() -> int:
    base_url = resolve_base_url()
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    client = AsyncOpenAI(base_url=base_url, api_key=os.getenv("OPENAI_API_KEY", ""))
    print(f"[OK] base_url={base_url} model={model}")

    try:
        response = await client.images.generate(
            model=model,
            prompt=PROMPT,
            size=os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            quality=os.getenv("OPENAI_IMAGE_QUALITY", "low"),
            n=1,
        )
    except OpenAIError as exc:
        print(f"[FAIL] {base_url} ({model}): {exc}", file=sys.stderr)
        return 1

    if not response.data:
        print("[FAIL] response contained no image data", file=sys.stderr)
        return 1

    try:
        path = await save_image(response.data[0], OUTPUT_DIR)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[FAIL] could not save image: {exc}", file=sys.stderr)
        return 1

    print(f"[OK] saved image -> {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
