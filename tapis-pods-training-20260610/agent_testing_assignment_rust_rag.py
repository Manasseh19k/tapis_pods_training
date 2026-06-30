
import os
import time
from contextlib import asynccontextmanager

import chromadb
from chromadb import EmbeddingFunction, Documents, Embeddings
from openai import OpenAI
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from pydantic import BaseModel

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.ui.ag_ui import AGUIAdapter


# Configuration
BASE_URL = os.environ.get("BASE_URL")
API_KEY  = os.environ.get("OPENAI_API_KEY")

MODEL_ID = "gpt-oss-120b"
EMBED_MODEL = "E5-Mistral-7B-Instruct"
BOOK_PATH = "Rust Atomics and Locks.txt"
DB_PATH = "./my_chroma_db"
COLLECTION_NAME = "rust_atomics_book"

CHUNK_SIZE = 200   # words per chunk
OVERLAP = 40       # words shared between neighbors

# Model + agent
model = OpenAIChatModel(
    MODEL_ID,
    provider=LiteLLMProvider(api_base=BASE_URL, api_key=API_KEY),
)

agent = Agent(
    model,
    system_prompt=(
        "You are an expert on the book 'Rust Atomics and Locks' by Mara Bos. "
        "Always answer using the search_book tool to ground your response in the "
        "book's actual text. If the retrieved passages do not contain the answer, "
        "say so rather than guessing."
    ),
)

# Embedding function (one string per request, with backoff)
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

class StringEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name, max_retries=6, base_delay=2.0, pause=0.2):
        self.model_name = model_name
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.pause = pause

    def _embed_one(self, text):
        for attempt in range(self.max_retries):
            try:
                resp = client.embeddings.create(model=self.model_name, input=text)
                emb = resp.data[0].embedding
                if emb is None:                      # if endpoint returns null
                    raise RuntimeError("null embedding")
                return emb
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                wait = self.base_delay * (2 ** attempt)   # exponential backoff
                print(f"  retry {attempt+1} after error: {e} (waiting {wait:.0f}s)")
                time.sleep(wait)

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for text in input:
            embeddings.append(self._embed_one(text))
            time.sleep(self.pause)                  # gentle throttle between calls
        return embeddings


embedding_function = StringEmbeddingFunction(EMBED_MODEL)

# Set during startup.
collection = None


# Build / load the index
def build_index():
    global collection
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_function,
    )

    if collection.count() > 0:
        print(f"Collection already has {collection.count()} chunks; skipping rebuild.")
        return

    with open(BOOK_PATH, "r", encoding="utf-8") as f:
        raw_text = f.read()

    words = raw_text.split()
    step = CHUNK_SIZE - OVERLAP

    chunks, ids, metadatas = [], [], []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start:start + CHUNK_SIZE])
        if chunk.strip():
            idx = len(chunks)
            chunks.append(chunk)
            ids.append(f"chunk_{idx}")
            metadatas.append({"source": BOOK_PATH, "chunk_index": idx})

    print(f"Created {len(chunks)} chunks.")

    B = 50
    for i in range(0, len(chunks), B):
        collection.add(
            documents=chunks[i:i + B],
            metadatas=metadatas[i:i + B],
            ids=ids[i:i + B],
        )
        print(f"Indexed {min(i + B, len(chunks))}/{len(chunks)}")


# Retrieval + agent tool
def retrieve(question: str, k: int = 4) -> str:
    res = collection.query(query_texts=[question], n_results=k)
    return "\n\n---\n\n".join(res["documents"][0])


@agent.tool_plain
def search_book(query: str) -> str:
    return retrieve(query)


# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    build_index()        # runs once when the server starts
    yield


app = FastAPI(title="Rust Atomics and Locks RAG", lifespan=lifespan)


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/")
async def run_agent(request: Request) -> Response:
    return await AGUIAdapter.dispatch_request(request, agent=agent)


class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask(q: Question):
    result = await agent.run(q.question)
    return {"answer": result.output}



