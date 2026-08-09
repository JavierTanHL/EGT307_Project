# EGT307 Three-Microservice Defect Detection System

Javier, Harsidh, Darrel, Azmi

This project uses the trained `component_classifier.keras` model from the
`component_classifier_fixed.ipynb` notebook to inspect products through a webcam
(or an uploaded image) and classify them as `GOOD` or `BAD`. It is built as three
independent microservices and can be deployed with either Docker Compose or
Kubernetes (Minikube).

## Three microservices

1. **Web/API Service**
   - Serves the website and the browser UI.
   - Requests webcam permission in the browser and captures a central square image.
   - Also accepts image **uploads** and **drag-and-drop** as alternatives to the webcam.
   - Calls the Inference Service, then forwards the result and image to the Storage Service.
   - Exposes the feedback endpoint used to correct predictions.

2. **Inference Service**
   - Loads `component_classifier.keras`.
   - Converts the image to RGB and centre-crops/resizes it to 224 × 224.
   - Returns `GOOD` or `BAD` with a confidence score.

3. **Storage Service**
   - Saves inspection records in SQLite (`/data/inspections.db`).
   - Saves every inspected image (`/data/images`).
   - Saves human-corrected feedback images into `savedImages/good` and `savedImages/bad`,
     and records the corrected label against the inspection record.
   - Returns inspection history and summary statistics.

## Features

- **Webcam capture** — capture a centred product image directly in the browser.
- **Image upload** — inspect an existing image file (JPG, PNG, or WebP) without the webcam.
- **Drag-and-drop** — drop an image onto the page to inspect it; the drop zone also
  opens a file picker when clicked.
- **Inspection history** — a table of past inspections with result, confidence, and a
  link to view each stored image.
- **Human-in-the-loop feedback** — after each inspection, a `Good` / `Bad` control lets a
  user confirm or correct the prediction. The corrected image is saved into the matching
  folder for future retraining, and the correction is written back to the database.

All three input methods (webcam, upload, drag-and-drop) run through the same
inference → storage → feedback pipeline.

## Architecture

```text
Browser (webcam / upload / drag-drop)
      |
      v
Web/API Service :8000
      |                    |
      v                    v
Inference :8001       Storage :8002
TensorFlow model      SQLite + images + feedback folders
```
/Users/azmichaniago/Downloads/systemarchitecturediagram.png

The browser accesses the webcam through JavaScript. The Docker container does
not directly access the webcam.

## Model preparation

Run `component_classifier_fixed.ipynb` in a Python 3.11 environment with the
`combined_dataset/` folder (containing `good/` and `bad/` subfolders) next to the
notebook. Its final cell creates:

```text
component_classifier.keras
```

Copy that file to:

```text
models/component_classifier.keras
```

The training dataset is not included in the project because `combined_dataset.zip`
is about 344 MB. Keep it separately for training.

### Note for Apple Silicon (M-series) Macs

On ARM64 Macs the `tensorflow-cpu` package has no Linux wheel and the image build
will fail with "No matching distribution found for tensorflow-cpu". Use the plain
`tensorflow` package in `services/inference/requirements.txt` instead, which ships
an ARM64 build and is CPU-only on Apple Silicon.

## Week 16: Docker Compose

From the project root:

```bash
docker compose up --build
```

(Windows PowerShell users can also run `.\scripts\run-local.ps1`.)

Open:

```text
http://localhost:8080
```

The website will ask for webcam permission (this works over `localhost`, which
browsers treat as a secure context).

Useful checks:

```bash
docker compose ps
docker compose logs -f web inference storage
```

API documentation:

```text
Web/API:   http://localhost:8080/docs
Inference: http://localhost:8001/docs
Storage:   http://localhost:8002/docs
```

To keep the feedback images (`savedImages/good`, `savedImages/bad`) on the host
in Docker Compose, the storage service uses a bind mount to
`./services/storage/savedImages`.

## Week 17: Minikube

```bash
minikube start --cpus=4 --memory=5120
minikube addons enable metrics-server

minikube image build -t defect-web:1.0 -f services/web/Dockerfile .
minikube image build -t defect-inference:1.0 -f services/inference/Dockerfile .
minikube image build -t defect-storage:1.0 -f services/storage/Dockerfile .

kubectl apply -f k8s
kubectl get all -n defect-detection
kubectl get pvc -n defect-detection
kubectl get hpa -n defect-detection
```

> Memory note: `--memory=5120` (5 GB) is used instead of 6144 because Docker
> Desktop must have at least that much allocated, and 5 GB leaves headroom for
> Docker itself. Increase it if your Docker Desktop memory limit allows.

Use localhost for browser webcam permission:

```bash
kubectl port-forward service/web-service 8080:80 -n defect-detection
```

Open:

```text
http://localhost:8080
```

Demonstrate scaling:

```bash
kubectl scale deployment inference-deployment --replicas=2 -n defect-detection
kubectl get pods -l app=inference -n defect-detection
```

The HorizontalPodAutoscaler (`k8s/05-inference-hpa.yaml`) scales the inference
service between 1 and 3 replicas at 60% CPU. Automatic scaling requires
`metrics-server`; manual scaling with `kubectl scale` works regardless.

## Why this satisfies the architecture requirement

- **Modularity:** interface, AI inference, and persistence are independent services.
- **Scalability:** the stateless Inference Service can be scaled separately, and the
  HPA scales it automatically on CPU load.
- **Fault tolerance:** Docker restart policies and Kubernetes probes restart
  unhealthy services. If storage is unavailable, the AI prediction is still
  returned with a storage warning.
- **Persistence:** SQLite and saved images use a Docker volume in Compose and a
  Kubernetes PVC in Minikube.

## Storage persistence: Compose vs Kubernetes

- In **Docker Compose**, the feedback folders (`savedImages/good`, `savedImages/bad`)
  are bind-mounted to the host, so they appear directly in
  `services/storage/savedImages/`.
- In **Kubernetes**, the inspection database and inspected images live on the PVC
  (persistent), while the feedback folders are written to the storage pod's own
  filesystem. They survive pod restarts but not pod deletion. To make them fully
  durable, mount the PVC at `/app/savedImages` in the storage manifest.

## Important limitation

The notebook trains a whole-image binary classifier. It predicts whether the
captured product is good or bad; it does not draw the exact location of a defect.
Keep one product centred inside the webcam guide. Webcam lighting and backgrounds
may differ from the training dataset, so adding real webcam and feedback images to
future training will improve real-world accuracy. The `Good` / `Bad` feedback loop
is designed to collect exactly this corrected data over time.
