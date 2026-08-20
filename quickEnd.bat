@echo off
setlocal

cd /d "%~dp0"

:: Step 1: Kill running port-forward background processes
echo [1/3] Stopping background port-forwards...
taskkill /F /IM kubectl.exe >nul 2>&1
echo Port-forwards terminated.

:: Step 2: Delete Kubernetes resources in reverse deployment order
echo [2/3] Deleting Kubernetes manifests...
kubectl delete -f k8s\06-trainer.yaml --ignore-not-found
kubectl delete -f k8s\05-inference-hpa.yaml --ignore-not-found
kubectl delete -f k8s\04-web.yaml --ignore-not-found
kubectl delete -f k8s\03-inference.yaml --ignore-not-found
kubectl delete -f k8s\02-storage.yaml --ignore-not-found
kubectl delete -f k8s\01-configmap.yaml --ignore-not-found
kubectl delete -f k8s\00-namespace.yaml --ignore-not-found

:: Step 3: Optional Minikube shutdown
echo.
echo [3/3] Cleanup complete!
echo.
set /p STOP_MINIKUBE="Do you also want to stop the Minikube cluster? (Y/N): "
if /i "%STOP_MINIKUBE%"=="Y" (
    echo Stopping Minikube...
    minikube stop
)

echo.
echo ============================================================
echo All background processes killed and services removed.
echo ============================================================
pause