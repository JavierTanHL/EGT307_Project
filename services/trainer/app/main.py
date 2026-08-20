from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import tensorflow as tf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/custom_dataset"))
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/app/models"))
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://inference:8001").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
IMAGE_SIZE = (224, 224)
MAX_IMAGE_BYTES = 8 * 1024 * 1024

DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Trainer Service", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

training_status: dict[str, Any] = {"item_name": None, "state": "idle", "epoch": 0, "total_epochs": 0, "val_accuracy": None, "error": None, "reload_ok": None, "reload_error": None}
training_lock = threading.Lock()


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"service": "trainer", "status": "ok", "training": training_status}


@app.post("/api/upload")
async def upload(item_name: str = Form(...), category: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    if category not in {"good", "bad"}:
        raise HTTPException(status_code=400, detail="category must be 'good' or 'bad'.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large.")
    if (file.content_type or "") not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Unsupported image type.")

    target_dir = DATA_DIR / item_name / category
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = file.filename or "upload.jpg"
    (target_dir / filename).write_bytes(image_bytes)

    return {"saved": True, "item_name": item_name, "category": category, "filename": filename}


@app.get("/api/dataset")
async def dataset(item_name: str) -> dict[str, Any]:
    good_dir = DATA_DIR / item_name / "good"
    bad_dir = DATA_DIR / item_name / "bad"
    good_count = len(list(good_dir.glob("*"))) if good_dir.exists() else 0
    bad_count = len(list(bad_dir.glob("*"))) if bad_dir.exists() else 0
    return {"item_name": item_name, "good": good_count, "bad": bad_count}


@app.post("/api/train")
async def train(item_name: str = Form(...)) -> dict[str, Any]:
    item_dir = DATA_DIR / item_name
    good_count = len(list((item_dir / "good").glob("*"))) if (item_dir / "good").exists() else 0
    bad_count = len(list((item_dir / "bad").glob("*"))) if (item_dir / "bad").exists() else 0
    if good_count < 2 or bad_count < 2:
        raise HTTPException(status_code=400, detail="Need at least a few images in both good and bad before training.")

    with training_lock:
        if training_status["state"] == "running":
            raise HTTPException(status_code=409, detail="A training run is already in progress.")
        training_status.update({"item_name": item_name, "state": "running", "epoch": 0, "total_epochs": 40, "val_accuracy": None, "error": None, "reload_ok": None, "reload_error": None})

    thread = threading.Thread(target=run_training, args=(item_name,), daemon=True)
    thread.start()
    return {"started": True, "item_name": item_name}


@app.get("/api/train/status")
async def train_status() -> dict[str, Any]:
    return training_status


@app.get("/api/models")
async def models() -> dict[str, Any]:
    files = sorted(p.name for p in MODELS_DIR.glob("*.keras"))
    return {"models": files}


@app.get("/api/models/{filename}/download")
async def download_model(filename: str) -> FileResponse:
    model_path = MODELS_DIR / filename
    if not model_path.exists() or model_path.suffix != ".keras":
        raise HTTPException(status_code=404, detail="Model not found.")
    return FileResponse(model_path, filename=filename)


@app.delete("/api/models/{filename}")
async def delete_model(filename: str) -> dict[str, Any]:
    if not filename.endswith(".keras") or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid model filename.")

    model_path = MODELS_DIR / filename
    if not model_path.exists():
        raise HTTPException(status_code=404, detail="Model not found.")

    try:
        model_path.unlink()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {exc}")

    reload_ok = True
    reload_error = None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{INFERENCE_URL}/models/reload")
            res.raise_for_status()
    except Exception as exc:
        reload_ok = False
        reload_error = str(exc)

    return {
        "deleted": True,
        "filename": filename,
        "reload_ok": reload_ok,
        "reload_error": reload_error,
    }



class ProgressCallback(tf.keras.callbacks.Callback):
    def __init__(self, epoch_offset: int) -> None:
        super().__init__()
        self.epoch_offset = epoch_offset

    def on_epoch_end(self, epoch: int, logs: dict[str, float] | None = None) -> None:
        logs = logs or {}
        training_status["epoch"] = self.epoch_offset + epoch + 1
        training_status["val_accuracy"] = round(float(logs.get("val_accuracy", 0.0)), 4)


def run_training(item_name: str) -> None:
    try:
        data_dir = DATA_DIR / item_name

        good_count = len(list((data_dir / "good").glob("*"))) if (data_dir / "good").exists() else 0
        bad_count = len(list((data_dir / "bad").glob("*"))) if (data_dir / "bad").exists() else 0

        if good_count >= 5 and bad_count >= 5:
            raw_train_ds = tf.keras.utils.image_dataset_from_directory(
                data_dir, validation_split=0.2, subset="training", seed=42,
                image_size=IMAGE_SIZE, batch_size=32
            )
            raw_val_ds = tf.keras.utils.image_dataset_from_directory(
                data_dir, validation_split=0.2, subset="validation", seed=42,
                image_size=IMAGE_SIZE, batch_size=32
            )
        else:
            raw_train_ds = tf.keras.utils.image_dataset_from_directory(
                data_dir, seed=42,
                image_size=IMAGE_SIZE, batch_size=32
            )
            raw_val_ds = tf.keras.utils.image_dataset_from_directory(
                data_dir, seed=42,
                image_size=IMAGE_SIZE, batch_size=32
            )

        labels = np.concatenate([y.numpy() for _, y in raw_train_ds])
        counts = np.bincount(labels, minlength=2)
        total = counts.sum()
        class_weight = {0: total / (2 * max(counts[0], 1)), 1: total / (2 * max(counts[1], 1))}

        AUTOTUNE = tf.data.AUTOTUNE
        data_augmentation = tf.keras.Sequential([
            tf.keras.layers.RandomFlip("horizontal_and_vertical"),
            tf.keras.layers.RandomRotation(0.15),
            tf.keras.layers.RandomZoom(0.15),
            tf.keras.layers.RandomContrast(0.1),
        ])
        train_ds = raw_train_ds.map(lambda x, y: (data_augmentation(x, training=True), y), num_parallel_calls=AUTOTUNE)
        train_ds = train_ds.cache().shuffle(1000).prefetch(AUTOTUNE)
        val_ds = raw_val_ds.cache().prefetch(AUTOTUNE)

        base_model = tf.keras.applications.MobileNetV2(input_shape=IMAGE_SIZE + (3,), include_top=False, weights="imagenet")
        base_model.trainable = False
        preprocess_input = tf.keras.applications.mobilenet_v2.preprocess_input

        inputs = tf.keras.Input(shape=IMAGE_SIZE + (3,))
        x = preprocess_input(inputs)
        x = base_model(x, training=False)
        x = tf.keras.layers.GlobalAveragePooling2D()(x)
        x = tf.keras.layers.Dropout(0.3)(x)
        x = tf.keras.layers.Dense(128, activation="relu")(x)
        x = tf.keras.layers.Dropout(0.3)(x)
        outputs = tf.keras.layers.Dense(1, activation="sigmoid")(x)
        model = tf.keras.Model(inputs, outputs)

        callbacks = [
            tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True),
            tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=2, min_lr=1e-6),
        ]

        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3), loss="binary_crossentropy", metrics=["accuracy"])
        model.fit(train_ds, validation_data=val_ds, epochs=25, class_weight=class_weight, callbacks=callbacks + [ProgressCallback(0)])

        base_model.trainable = True
        fine_tune_at = len(base_model.layers) - 30
        for layer in base_model.layers[:fine_tune_at]:
            layer.trainable = False

        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5), loss="binary_crossentropy", metrics=["accuracy"])
        model.fit(train_ds, validation_data=val_ds, epochs=15, class_weight=class_weight, callbacks=callbacks + [ProgressCallback(25)])

        model.save(MODELS_DIR / f"{item_name}_classifier.keras")
        reload_ok = True
        reload_error = None
        try:
            httpx.post(f"{INFERENCE_URL}/models/reload", timeout=30.0).raise_for_status()
        except Exception as exc:
            reload_ok = False
            reload_error = str(exc)
        training_status.update({"state": "done", "reload_ok": reload_ok, "reload_error": reload_error})
    except Exception as exc:
        training_status.update({"state": "error", "error": str(exc)})
