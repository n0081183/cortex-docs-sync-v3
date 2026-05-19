#!/bin/bash
set -e

echo "[SYSTEM] Rozpoczynam przygotowanie środowiska RunPod..."
pip install --break-system-packages -e .
pip install --break-system-packages -r requirements-runpod.txt

echo "[SYSTEM] Czyszczenie środowiska ONNX..."
pip uninstall -y onnxruntime onnxruntime-gpu || true
# Instalacja dedykowanej paczki dla akceleracji CUDA
pip install --break-system-packages onnxruntime-gpu --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

echo "[SYSTEM] Faza 1: Pobieranie dokumentacji Cortex (Scraper z trybem Jitter)"
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export URLLIB3_RETRY_MAX=15
export URLLIB3_RETRY_BACKOFF_FACTOR=2.5

python3 -m cortex_docs_sync --rate-limit 0.5 || echo "[WARNING] Scraper napotkał problemy, ale wymuszam kontynuację..."

echo "[SYSTEM] Faza 2: Przetwarzanie i wektoryzacja danych (AI)"
python3 worker.py

echo "[SUKCES] Całkowity proces zakończony pomyślnie."
