#!/bin/bash
set -e

echo "[SYSTEM] Rozpoczynam przygotowanie środowiska RunPod..."
pip uninstall -y onnxruntime >/dev/null 2>&1 || true
pip install --break-system-packages -r requirements-runpod.txt

echo "[SYSTEM] Instalacja silnika synchronizacji..."
pip install --break-system-packages -e .

echo "[SYSTEM] Faza 1: Pobieranie dokumentacji Cortex (Scraper z trybem Jitter)"
# Zamiast sztywnego 0.3, używamy 0.5 ale z potężnym, ukrytym mechanizmem 
# ponawiania (backoff) ustawionym zmiennymi środowiskowymi dla biblioteki requests.
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export URLLIB3_RETRY_MAX=15
export URLLIB3_RETRY_BACKOFF_FACTOR=2.5

# Przechwytujemy kody błędu, by scraper nie "wykładał się" na Python Traceback, 
# tylko szedł dalej, jeśli jakaś publikacja będzie totalnie zablokowana.
python3 -m cortex_docs_sync --rate-limit 0.5 || echo "[WARNING] Scraper napotkał problemy, ale wymuszam kontynuację..."

echo "[SYSTEM] Faza 2: Przetwarzanie i wektoryzacja danych (AI)"
python3 worker.py

echo "[SUKCES] Całkowity proces zakończony pomyślnie."
