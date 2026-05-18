import os
# Uciszamy logi onnxruntime, żeby nie śmieciły w konsoli aplikacji
os.environ["ORT_LOGGING_LEVEL"] = "3"

import tarfile
import re
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from fastembed import TextEmbedding
import uuid
from html.parser import HTMLParser

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
    def get_text(self):
        return " ".join("".join(self.text).split())

def clean_html(html_content):
    try:
        parser = HTMLTextExtractor()
        parser.feed(html_content)
        return parser.get_text()
    except:
        return " ".join(re.sub(r'<[^>]+>', ' ', html_content).split())

def chunk_text(text, chunk_size_words=300, overlap_words=50):
    words = text.split()
    if not words: return []
    chunks = []
    for i in range(0, len(words), chunk_size_words - overlap_words):
        chunk = " ".join(words[i:i + chunk_size_words])
        if chunk.strip(): chunks.append(chunk)
        if i + chunk_size_words >= len(words): break
    return chunks

def run_ingest():
    print("[SYSTEM] Startuje proces wektoryzacji (GPU)...")
    output_tar_path = "/workspace/cortex_index.tar.gz"
    
    docs_dir = Path("cortex_docs")
    if not docs_dir.exists():
        print("[BŁĄD KRYTYCZNY] Brak pobranych dokumentów.")
        return
        
    data_dir = Path("/tmp/qdrant_sync")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    client = QdrantClient(path=str(data_dir))
    collection_name = "cortex_docs"
    
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
        
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
    )
    
    html_files = list(docs_dir.rglob("*.html"))
    print(f"[SYSTEM] Wykryto publikacje: {len(html_files)}")
    
    embedding_model = TextEmbedding("intfloat/multilingual-e5-large")
    all_chunks, all_payloads = [], []
    
    for idx, file_path in enumerate(html_files, 1):
        try:
            clean_txt = clean_html(file_path.read_text(encoding='utf-8', errors='ignore'))
            for c_idx, chunk in enumerate(chunk_text(clean_txt)):
                all_chunks.append(chunk)
                all_payloads.append({"title": file_path.stem, "product": file_path.parent.name, "text": chunk})
        except: pass

    print(f"[PROGRESS] RTX 4090 generuje {len(all_chunks)} wektorów...")
    embeddings = list(embedding_model.embed(all_chunks, batch_size=64))
    
    print("[SYSTEM] Zapis do bazy danych wektorowych...")
    points = [PointStruct(id=str(uuid.uuid4()), vector=v.tolist(), payload=all_payloads[i]) for i, v in enumerate(embeddings)]
        
    for i in range(0, len(points), 1000):
        client.upsert(collection_name=collection_name, points=points[i:i+1000])
        
    print("[SYSTEM] Kompresja paczki indeksu...")
    with tarfile.open(output_tar_path, "w:gz") as tar:
        tar.add(str(data_dir), arcname="qdrant_sync")
        
    print("[SUKCES] Baza gotowa i zapakowana!")

if __name__ == "__main__":
    run_ingest()
