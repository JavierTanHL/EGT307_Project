from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "/data/inspections.db"))
IMAGE_DIRECTORY = Path(os.getenv("IMAGE_DIRECTORY", "/data/images"))
SAVED_IMAGES_DIRECTORY = Path(os.getenv("SAVED_IMAGES_DIRECTORY", "/app/savedImages"))
MAX_IMAGE_BYTES = 8 * 1024 * 1024

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
(SAVED_IMAGES_DIRECTORY / "good").mkdir(parents=True, exist_ok=True)
(SAVED_IMAGES_DIRECTORY / "bad").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Storage Service", version="1.0.0")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialise() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                prediction TEXT NOT NULL,
                confidence REAL NOT NULL,
                good_probability REAL NOT NULL,
                bad_probability REAL NOT NULL,
                source TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_image_name TEXT
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(inspections)")}
        if "corrected_label" not in columns:
            connection.execute("ALTER TABLE inspections ADD COLUMN corrected_label TEXT")
        connection.commit()


initialise()


@app.get("/health")
async def health() -> dict[str, Any]:
    with closing(connect()) as connection:
        connection.execute("SELECT 1").fetchone()
    return {
        "service": "storage",
        "status": "ok",
        "database_path": str(DATABASE_PATH),
    }


@app.post("/inspections", status_code=201)
async def create_inspection(
    prediction: str = Form(...),
    confidence: float = Form(...),
    good_probability: float = Form(...),
    bad_probability: float = Form(...),
    source: str = Form("webcam"),
    original_filename: str = Form("capture.jpg"),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    prediction = prediction.upper()
    if prediction not in {"GOOD", "BAD"}:
        raise HTTPException(status_code=422, detail="Prediction must be GOOD or BAD.")

    for name, value in {
        "confidence": confidence,
        "good_probability": good_probability,
        "bad_probability": bad_probability,
    }.items():
        if not 0 <= value <= 1:
            raise HTTPException(status_code=422, detail=f"{name} must be 0 to 1.")

    stored_name = None
    if file is not None:
        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(file.content_type or "")

        if extension is None:
            raise HTTPException(status_code=415, detail="Unsupported image type.")

        image_bytes = await file.read()
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is too large.")

        stored_name = f"{uuid.uuid4().hex}{extension}"
        (IMAGE_DIRECTORY / stored_name).write_bytes(image_bytes)

    created_at = datetime.now(timezone.utc).isoformat()

    with closing(connect()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO inspections (
                created_at, prediction, confidence, good_probability,
                bad_probability, source, original_filename, stored_image_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                prediction,
                confidence,
                good_probability,
                bad_probability,
                source,
                original_filename,
                stored_name,
            ),
        )
        connection.commit()
        inspection_id = int(cursor.lastrowid)

    return {
        "id": inspection_id,
        "created_at": created_at,
        "prediction": prediction,
        "confidence": confidence,
        "good_probability": good_probability,
        "bad_probability": bad_probability,
        "source": source,
        "original_filename": original_filename,
        "image_available": stored_name is not None,
    }


@app.get("/inspections")
async def inspections(
    limit: int = Query(25, ge=1, le=100),
) -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, prediction, confidence, good_probability,
                   bad_probability, source, original_filename, stored_image_name
            FROM inspections
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [serialise(row) for row in rows]


@app.get("/inspections/{inspection_id}/image")
async def inspection_image(inspection_id: int) -> FileResponse:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT stored_image_name FROM inspections WHERE id = ?",
            (inspection_id,),
        ).fetchone()

    if row is None or not row["stored_image_name"]:
        raise HTTPException(status_code=404, detail="Stored image not found.")

    image_path = IMAGE_DIRECTORY / row["stored_image_name"]
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Stored image file is missing.")

    return FileResponse(image_path)


@app.post("/inspections/{inspection_id}/feedback")
async def feedback(inspection_id: int, label: str = Form(...)) -> dict[str, Any]:
    label = label.upper()
    if label not in {"GOOD", "BAD"}:
        raise HTTPException(status_code=422, detail="Label must be GOOD or BAD.")

    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT stored_image_name FROM inspections WHERE id = ?",
            (inspection_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Inspection not found.")

        saved_path = None
        stored_name = row["stored_image_name"]
        if stored_name:
            source_path = IMAGE_DIRECTORY / stored_name
            if source_path.exists():
                target_dir = SAVED_IMAGES_DIRECTORY / label.lower()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / f"{inspection_id}_{stored_name}"
                target_path.write_bytes(source_path.read_bytes())
                saved_path = str(target_path)

        connection.execute(
            "UPDATE inspections SET corrected_label = ? WHERE id = ?",
            (label, inspection_id),
        )
        connection.commit()

    return {"id": inspection_id, "corrected_label": label, "saved_image_path": saved_path}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    with closing(connect()) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN prediction = 'GOOD' THEN 1 ELSE 0 END) AS good,
                SUM(CASE WHEN prediction = 'BAD' THEN 1 ELSE 0 END) AS bad,
                AVG(confidence) AS average_confidence
            FROM inspections
            """
        ).fetchone()

    return {
        "total": int(row["total"] or 0),
        "good": int(row["good"] or 0),
        "bad": int(row["bad"] or 0),
        "average_confidence": float(row["average_confidence"] or 0),
    }


def serialise(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "prediction": row["prediction"],
        "confidence": row["confidence"],
        "good_probability": row["good_probability"],
        "bad_probability": row["bad_probability"],
        "source": row["source"],
        "original_filename": row["original_filename"],
        "image_available": row["stored_image_name"] is not None,
    }
