from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

INFERENCE_URL = os.getenv("INFERENCE_URL", "http://inference:8001").rstrip("/")
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage:8002").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
MAX_IMAGE_BYTES = 8 * 1024 * 1024

app = FastAPI(title="Web and API Service", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    dependencies: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in {
            "inference": f"{INFERENCE_URL}/health",
            "storage": f"{STORAGE_URL}/health",
        }.items():
            try:
                response = await client.get(url)
                dependencies[name] = {
                    "reachable": True,
                    "status_code": response.status_code,
                    "details": response.json(),
                }
            except Exception as exc:
                dependencies[name] = {"reachable": False, "error": str(exc)}

    return {"service": "web", "status": "ok", "dependencies": dependencies}


@app.get("/api/models")
async def models() -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(f"{INFERENCE_URL}/models")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/inspect")
async def inspect(file: UploadFile = File(...), item: str = Form("component")) -> dict[str, Any]:
    image_bytes = await file.read()
    content_type = file.content_type or "image/jpeg"
    filename = file.filename or "webcam-capture.jpg"

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Captured image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Captured image is too large.")
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Unsupported image type.")

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(
                f"{INFERENCE_URL}/predict",
                data={"item": item},
                files={"file": (filename, image_bytes, content_type)},
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Inference Service unavailable: {exc}",
            ) from exc

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=_error_text(response),
            )

        prediction = response.json()
        stored = False
        storage_record = None
        storage_error = None

        try:
            storage_response = await client.post(
                f"{STORAGE_URL}/inspections",
                data={
                    "prediction": prediction["prediction"],
                    "confidence": str(prediction["confidence"]),
                    "good_probability": str(prediction["good_probability"]),
                    "bad_probability": str(prediction["bad_probability"]),
                    "source": "webcam",
                    "original_filename": filename,
                },
                files={"file": (filename, image_bytes, content_type)},
            )
            storage_response.raise_for_status()
            stored = True
            storage_record = storage_response.json()
        except Exception as exc:
            storage_error = str(exc)

    return {
        "prediction": prediction,
        "storage_saved": stored,
        "storage_record": storage_record,
        "storage_error": storage_error,
    }


@app.get("/api/history")
async def history(limit: int = 25) -> Any:
    limit = max(1, min(limit, 100))
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                f"{STORAGE_URL}/inspections",
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/stats")
async def stats() -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(f"{STORAGE_URL}/stats")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/inspections/{inspection_id}/image")
async def stored_image(inspection_id: int) -> Response:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{STORAGE_URL}/inspections/{inspection_id}/image"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=_error_text(response),
        )

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/jpeg"),
    )


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("detail", payload))
    except Exception:
        return response.text or "Unknown service error."
