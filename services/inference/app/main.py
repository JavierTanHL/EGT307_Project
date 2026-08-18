from __future__ import annotations

import io
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import tensorflow as tf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps

MODELS_DIR = Path(os.getenv("MODELS_DIR", "/app/models"))
DEFAULT_ITEM = os.getenv("DEFAULT_ITEM", "component")
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE", "224"))
GOOD_THRESHOLD = float(os.getenv("GOOD_THRESHOLD", "0.5"))
MAX_IMAGE_BYTES = 8 * 1024 * 1024

models: dict[str, tf.keras.Model] = {}
load_errors: dict[str, str] = {}
prediction_lock = threading.Lock()


def item_name_from_path(model_path: Path) -> str:
    name = model_path.stem
    return name[: -len("_classifier")] if name.endswith("_classifier") else name


def load_models() -> None:
    models.clear()
    load_errors.clear()
    if not MODELS_DIR.exists():
        load_errors["_directory"] = f"Models directory not found at {MODELS_DIR}."
        return
    for model_path in sorted(MODELS_DIR.glob("*.keras")):
        item = item_name_from_path(model_path)
        try:
            models[item] = tf.keras.models.load_model(model_path)
        except Exception as exc:
            load_errors[item] = str(exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_models()
    yield


app = FastAPI(
    title="Inference Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "service": "inference",
        "status": "ok",
        "models_loaded": sorted(models.keys()),
        "load_errors": load_errors,
        "models_dir": str(MODELS_DIR),
        "image_size": IMAGE_SIZE,
        "good_threshold": GOOD_THRESHOLD,
    }


@app.get("/ready")
async def ready() -> dict[str, str]:
    if not models:
        raise HTTPException(status_code=503, detail=next(iter(load_errors.values()), "No models loaded."))
    return {"status": "ready"}


@app.get("/models")
async def list_models() -> dict[str, Any]:
    return {"items": sorted(models.keys()), "load_errors": load_errors}


@app.post("/models/reload")
async def reload_models() -> dict[str, Any]:
    load_models()
    return {"items": sorted(models.keys()), "load_errors": load_errors}


@app.post("/predict")
async def predict(file: UploadFile = File(...), item: str = Form(DEFAULT_ITEM)) -> dict[str, Any]:
    model = models.get(item)
    if model is None:
        raise HTTPException(
            status_code=503,
            detail=f"No model loaded for item '{item}'. Available: {sorted(models.keys()) or 'none'}.",
        )

    if (file.content_type or "") not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Unsupported image type.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large.")

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot decode image: {exc}") from exc

    image = ImageOps.fit(
        image,
        (IMAGE_SIZE, IMAGE_SIZE),
        method=Image.Resampling.BILINEAR,
        centering=(0.5, 0.5),
    )

    # MobileNetV2 preprocess_input is already inside the saved model graph.
    # Supply RGB values in the original 0–255 range.
    array = np.asarray(image, dtype=np.float32)
    batch = np.expand_dims(array, axis=0)

    with prediction_lock:
        output = model.predict(batch, verbose=0)

    good_probability = float(np.asarray(output).reshape(-1)[0])
    good_probability = min(max(good_probability, 0.0), 1.0)
    bad_probability = 1.0 - good_probability

    if good_probability >= GOOD_THRESHOLD:
        prediction = "GOOD"
        confidence = good_probability
    else:
        prediction = "BAD"
        confidence = bad_probability

    return {
        "item": item,
        "prediction": prediction,
        "confidence": round(confidence, 6),
        "good_probability": round(good_probability, 6),
        "bad_probability": round(bad_probability, 6),
        "threshold": GOOD_THRESHOLD,
        "input_shape": [IMAGE_SIZE, IMAGE_SIZE, 3],
    }

