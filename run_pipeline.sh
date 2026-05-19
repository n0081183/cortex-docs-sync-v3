#!/bin/bash
set -e

echo "[SYSTEM] Rozpoczynam przygotowanie środowiska RunPod..."
pip install --break-system-packages -e .
pip install --break-system-packages fastembed qdrant-client

echo "[SYSTEM] Czyszczenie konfliktów środowiska ONNX..."
# KRYTYCZNA POPRAWKA: Flaga --break-system-packages pozwala na usunięcie paczki w Ubuntu
pip uninstall -y --break-system-packages onnxruntime onnxruntime-gpu || true

pip install --break-system-packages --no-cache-dir --force-reinstall onnxruntime-gpu

export LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH

echo "[SYSTEM] Faza 1: Pobieranie dokumentacji Cortex..."
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export URLLIB3_RETRY_MAX=15
export URLLIB3_RETRY_BACKOFF_FACTOR=2.5

python3 -m cortex_docs_sync --rate-limit 0.5 || echo "[WARNING] Scraper napotkał problemy, ale wymuszam kontynuację..."

echo "[SYSTEM] Faza 2: Przetwarzanie i wektoryzacja danych (AI)"
python3 worker.py

echo "[SUKCES] Całkowity proces zakończony pomyślnie."
