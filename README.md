# EGT307 Three-Microservice Defect Detection System

This project uses the trained `component_classifier.keras` model from your
`component_classifier_fixed.ipynb` notebook.

## Three microservices

1. **Web/API Service**
   - Serves the website.
   - Requests webcam permission in the browser.
   - Captures a central square image.
   - Calls the Inference Service.
   - Sends the result to the Storage Service.

2. **Inference Service**
   - Loads `component_classifier.keras`.
   - Converts the image to RGB.
   - Centre-crops/resizes it to 224 × 224.
   - Returns `GOOD` or `BAD` with confidence.

3. **Storage Service**
   - Saves inspection records in SQLite.
   - Saves captured images.
   - Returns inspection history and summary statistics.

## Architecture

```text
Browser webcam
      |
      v
Web/API Service :8000
      |                    |
      v                    v
Inference :8001       Storage :8002
TensorFlow model      SQLite + images
```

The browser accesses the webcam through JavaScript. The Docker container does
not directly access the webcam.

## Model preparation

Run `component_classifier_fixed.ipynb`. Its final cell creates:

```text
component_classifier.keras
```

Copy that file to:

```text
models/component_classifier.keras
```

The dataset is not included in this project ZIP because `combined_dataset.zip`
is about 344 MB. Keep it separately for training.

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
http://localhost:8080
```

The website will ask for webcam permission.

Useful checks:

```powershell
docker compose ps
docker compose logs -f web inference storage
```

API documentation:

```text
Web/API:   http://localhost:8080/docs
Inference: http://localhost:8001/docs
Storage:   http://localhost:8002/docs
```

## Week 17: Minikube

```powershell
minikube start --cpus=4 --memory=6144
minikube addons enable metrics-server

minikube image build -t defect-web:1.0 -f services/web/Dockerfile .
minikube image build -t defect-inference:1.0 -f services/inference/Dockerfile .
minikube image build -t defect-storage:1.0 -f services/storage/Dockerfile .

kubectl apply -f k8s
kubectl get all -n defect-detection
kubectl get pvc -n defect-detection
kubectl get hpa -n defect-detection
```

Use localhost for browser webcam permission:

```powershell
kubectl port-forward service/web-service 8080:80 -n defect-detection
```

Open:

```text
http://localhost:8080
```

Demonstrate scaling:

```powershell
kubectl scale deployment inference-deployment --replicas=2 -n defect-detection
kubectl get pods -l app=inference -n defect-detection
```

## Why this satisfies the architecture requirement

- **Modularity:** interface, AI inference and persistence are independent.
- **Scalability:** the stateless Inference Service can be scaled separately.
- **Fault tolerance:** Docker restart policies and Kubernetes probes restart
  unhealthy services. If storage is unavailable, the AI prediction is still
  returned with a storage warning.
- **Persistence:** SQLite and saved images use a Docker volume and Kubernetes PVC.

## Important limitation

Your notebook trains a whole-image binary classifier. It predicts whether the
captured product is good or bad; it does not draw the exact location of a defect.
Keep one product centred inside the webcam guide. Webcam lighting and backgrounds
may differ from the training dataset, so adding webcam images to future training
will improve real-world accuracy.
