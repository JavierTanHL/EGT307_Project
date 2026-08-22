# EGT307 Defect Detection System

A four-microservice system that classifies a product as `GOOD` or `BAD` from a
webcam capture, stores the inspection history, and lets you train new
per-item classifiers from the browser — no notebook required after the
first model exists.

## Services

| Service       | Port | Role                                                                 |
|---------------|------|-----------------------------------------------------------------------|
| **Web/API** (Javier)  | 8000 | Serves the site, requests webcam access, calls Inference, then Storage. |
| **Inference** (Azmi) | 8001 | Loads every `\\\*.keras` model in `models/`, runs prediction, returns `GOOD`/`BAD` + confidence. |
| **Storage** (Darrel)  | 8002 | Saves inspection records + images in SQLite, serves history and stats. |
| **Trainer** (Harsidh)  | 8003 | Web UI to upload good/bad images per item and fine-tune a new classifier. |

1. **Web/API Service**
   - Serves the website and requests webcam permission in the browser.
   - Captures a centred square image and calls the Inference Service.
   - Sends the result to the Storage Service.
   - Also proxies model listing/reload/delete calls to the Inference Service.

2. **Inference Service**
   - On startup (and on `/models/reload`), loads every `\\\*.keras` file in
     `models/`. A file named `widget\\\_classifier.keras` is served as item
     `widget`; `component\\\_classifier.keras` is served as `component`.
   - Converts the captured image to RGB and centre-crops/resizes it to 224 × 224.
   - Returns `GOOD` or `BAD` with a confidence score for the requested item.

3. **Storage Service**
   - Saves inspection records in SQLite and saves captured images.
   - Returns inspection history and summary statistics.

4. **Trainer Service**
   - Lets you upload `good`/`bad` example images for a new item through a
     small web UI (`http://localhost:8003`).
   - Fine-tunes a MobileNetV2-based classifier on those images (transfer
     learning, then a fine-tuning pass) and saves it as
     `models/<item\\\_name>\\\_classifier.keras`.
   - Triggers the Inference Service to reload models once training finishes,
     so the new item becomes available immediately — no redeploy needed.

## Architecture

```text
Browser webcam
      |
      v
Web/API Service :8000
      |                    |
      v                    v
Inference :8001       Storage :8002
TensorFlow models      SQLite + images
      ^
      |
Trainer :8003  (uploads images, trains, saves to models/, triggers reload)
```

The browser accesses the webcam through JavaScript; the container itself
never touches the webcam.

## Model preparation

You have two ways to get a model into `models/`:

**Option A — train in the notebook (baseline model)**

Run `models/component\\\_classifier\\\_final.ipynb` (or
`component\\\_classifier\\\_fixed.ipynb`). Its final cell creates
`component\\\_classifier.keras`. Copy that file to:

```text
models/component_classifier.keras
```

The dataset is not included in this repo because `combined\\\_dataset.zip` is
about 344 MB. Keep it separately for training.

**Option B — train a new item from the Trainer web UI**

With the stack running, open `http://localhost:8003`, upload a handful of
`good` and `bad` images for a new item (at least 2 of each; 5+ recommended),
and start training. The resulting `<item\\\_name>\\\_classifier.keras` lands in
`models/` and the Inference Service picks it up automatically.

`requirements-training.txt` covers the notebook/CLI training path; the
Trainer service installs its own dependencies inside its container image.

## Week 16: Docker Compose

PowerShell:

```powershell
.\scripts\run-local.ps1
```

Or:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8080   # Web/API (webcam UI)
http://localhost:8003   # Trainer UI
```

The website will ask for webcam permission.

Useful checks:

```powershell
docker compose ps
docker compose logs -f web inference storage trainer
```

API documentation:

```text
Web/API:   http://localhost:8080/docs
Inference: http://localhost:8001/docs
Storage:   http://localhost:8002/docs
Trainer:   http://localhost:8003/docs
```

## Week 17: Minikube

The fastest path is the bundled scripts, which build all four images, load
them into Minikube, apply every manifest, and open both UIs:

```powershell
quickStart.bat
```

```powershell
quickEnd.bat
```

Or do it by hand:

```powershell
minikube start --cpus=4 --memory=6144
minikube addons enable metrics-server

minikube image build -t defect-web:1.0 -f services/web/Dockerfile .
minikube image build -t defect-inference:1.0 -f services/inference/Dockerfile .
minikube image build -t defect-storage:1.0 -f services/storage/Dockerfile .
minikube image build -t defect-trainer:1.0 -f services/trainer/Dockerfile .

kubectl apply -f k8s
kubectl get all -n defect-detection
kubectl get pvc -n defect-detection
kubectl get hpa -n defect-detection
```

Use localhost for browser webcam permission:

```powershell
kubectl port-forward service/web-service 8080:80 -n defect-detection
kubectl port-forward service/trainer-service 8003:8003 -n defect-detection
```

Open:

```text
http://localhost:8080   # Web/API
http://localhost:8003   # Trainer
```

Demonstrate scaling:

```powershell
kubectl scale deployment inference-deployment --replicas=2 -n defect-detection
kubectl get pods -l app=inference -n defect-detection
```

The Inference Service also has an HPA (`k8s/05-inference-hpa.yaml`) that
scales it between 1 and 3 replicas at 60% CPU utilisation.

## Why this satisfies the architecture requirement

- **Modularity:** interface, AI inference, persistence, and training are
  four independently deployable services.
- **Scalability:** the stateless Inference Service can be scaled
  independently, manually or via its HPA.
- **Fault tolerance:** Docker restart policies and Kubernetes probes restart
  unhealthy services. If storage is unavailable, the AI prediction is still
  returned with a storage warning.
- **Persistence:** SQLite/images, models, and the custom training dataset
  each use their own Docker volume / Kubernetes PVC
  (`defect-data`, `models-pvc`, `custom-dataset-pvc`).
- **Extensibility:** new item types can be added from the Trainer UI at
  runtime, without rebuilding or redeploying the Inference Service.

## Important limitation

Each model is a whole-image binary classifier. It predicts whether the
captured product is good or bad; it does not draw the exact location of a
defect. Keep one product centred inside the webcam guide. Webcam lighting
and backgrounds may differ from the training dataset, so adding webcam
images through the Trainer service will improve real-world accuracy for
that item.
