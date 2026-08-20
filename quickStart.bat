@echo off
setlocal

:: Step 1: Ensure Docker is ready before proceeding
echo [1/6] Checking Docker status...
:CHECK_DOCKER
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Waiting for Docker daemon to initialize...
    timeout /t 3 /nobreak >nul
    goto CHECK_DOCKER
)
echo Docker is ready!

:: Step 2: Start Minikube if not already running
echo [2/6] Checking Minikube status...
minikube status | findstr /i "Running" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Starting Minikube...
    minikube start --driver=docker
) else (
    echo Minikube is already running.
)

:: Step 3: Build Docker images
cd /d "%~dp0"
echo [3/6] Building Docker images...
docker build -t defect-web:1.0 -f services\web\Dockerfile .
docker build -t defect-inference:1.0 -f services\inference\Dockerfile .
docker build -t defect-storage:1.0 -f services\storage\Dockerfile .
docker build -t defect-trainer:1.0 -f services\trainer\Dockerfile .

:: Step 4: Load images into Minikube
echo [4/6] Loading images into Minikube cluster...
minikube image load defect-web:1.0
minikube image load defect-inference:1.0
minikube image load defect-storage:1.0
minikube image load defect-trainer:1.0

:: Step 5: Apply all Kubernetes manifests in order
echo [5/6] Deploying Kubernetes manifests...
kubectl apply -f k8s\00-namespace.yaml
kubectl apply -f k8s\01-configmap.yaml
kubectl apply -f k8s\02-storage.yaml
kubectl apply -f k8s\03-inference.yaml
kubectl apply -f k8s\04-web.yaml
kubectl apply -f k8s\05-inference-hpa.yaml
kubectl apply -f k8s\06-trainer.yaml

:: Step 6: Wait for deployments and open websites
echo [6/6] Waiting for deployments to be ready...
kubectl rollout status deployment/web-deployment -n defect-detection --timeout=120s
kubectl rollout status deployment/trainer-deployment -n defect-detection --timeout=120s

echo.
echo Launching port-forwards and opening websites...
start /b cmd /c kubectl port-forward -n defect-detection svc/web-service 8080:80 >nul 2>&1
start /b cmd /c kubectl port-forward -n defect-detection svc/trainer-service 8003:8003 >nul 2>&1

timeout /t 2 /nobreak >nul
start http://localhost:8080
start http://localhost:8003

echo.
echo ============================================================
echo All services applied and websites launched:
echo   - Web:     http://localhost:8080
echo   - Trainer: http://localhost:8003
echo ============================================================
pause