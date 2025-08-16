from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
import time

app = FastAPI(title="crypto-ai-bot")

@app.get("/health")
def health():
    return JSONResponse({"status": "healthy", "degradation_level": "none", "components": {"mode":"paper","events":{"status":"not_configured"}}})

@app.get("/metrics")
def metrics():
    return PlainTextResponse("", media_type="text/plain; version=0.0.4; charset=utf-8")