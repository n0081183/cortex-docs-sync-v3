#!/bin/bash
set -e # Zatrzymuje skrypt w przypadku błędu na którymkolwiek etapie

echo "[SYSTEM] Rozpoczynam przygotowanie środowiska RunPod..."
pip uninstall -y onnxruntime >/dev/null 2>&1 || true
pip install --break-system-packages -r requirements-runpod.txt

echo "[SYSTEM] Instalacja silnika synchronizacji..."
pip install --break-system-packages -e .

echo "[SYSTEM] Faza 1: Pobieranie dokumentacji Cortex (Scraper)"
python3 -m cortex_docs_sync

echo "[SYSTEM] Faza 2: Przetwarzanie i wektoryzacja danych (AI)"
python3 worker.py

echo "[SUKCES] Całkowity proces zakończony pomyślnie."
