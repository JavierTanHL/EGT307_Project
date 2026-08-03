from __future__ import annotations

import io
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import tensorflow as tf
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, ImageOps

MODEL_PATH = Path(os.getenv("MODEL_PATH", "/app/models/component_classifier.keras"))
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE", "224"))
GOOD_THRESHOLD = float(os.getenv("GOOD_THRESHOLD", "0.5"))
MAX_IMAGE_BYTES = 8 * 1024 * 1024

model: tf.keras.Model | None = None
load_error: str | None = None
prediction_lock = threading.Lock()


def load_model() -> None:
    global model, load_error
    try:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model not found at {MODEL_PATH}. Run the notebook and copy "
                "component_classifier.keras into the models folder."
            )
        model = tf.keras.models.load_model(MODEL_PATH)
        load_error = None
    except Exception as exc:
        model = None
        load_error = str(exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_model()
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
        "model_loaded": model is not None,
        "model_path": str(MODEL_PATH),
        "image_size": IMAGE_SIZE,
        "good_threshold": GOOD_THRESHOLD,
        "load_error": load_error,
    }


@app.get("/ready")
async def ready() -> dict[str, str]:
    if model is None:
        raise HTTPException(status_code=503, detail=load_error or "Model not loaded.")
    return {"status": "ready"}


@app.post("/predict")
async def predict(file: UploadFile = File(...)) -> dict[str, Any]:
    if model is None:
        raise HTTPException(status_code=503, detail=load_error or "Model not loaded.")

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
        "prediction": prediction,
        "confidence": round(confidence, 6),
        "good_probability": round(good_probability, 6),
        "bad_probability": round(bad_probability, 6),
        "threshold": GOOD_THRESHOLD,
        "input_shape": [IMAGE_SIZE, IMAGE_SIZE, 3],
    }
