"""Optional: lets a phone app (Flutter, React Native...) ask for results.
Needs `pip install fastapi uvicorn`. Run from src/:  uvicorn wearables.api.app:app --reload
"""
from dataclasses import asdict

from fastapi import FastAPI

from wearables import config
from wearables.ingest.mock_source import MockSource  # swap for the real source later
from wearables.pipeline import run

app = FastAPI(title="Wearables Software API")


@app.get("/insights")
def insights():
    _, found = run(MockSource())
    return {"disclaimer": config.DISCLAIMER, "insights": [asdict(i) for i in found]}
