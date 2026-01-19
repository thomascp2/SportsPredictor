"""
SportsPredictor API
===================
FastAPI backend serving prediction data for mobile app.

Run with: uvicorn api.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import CORS_ORIGINS, API_VERSION, API_TITLE, API_DESCRIPTION
from api.routers import picks, scores, parlays, performance, players

# Create FastAPI app
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
)

# Configure CORS for Expo/React Native
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(picks.router, prefix="/api/picks", tags=["picks"])
app.include_router(scores.router, prefix="/api/scores", tags=["scores"])
app.include_router(parlays.router, prefix="/api/parlays", tags=["parlays"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(players.router, prefix="/api/players", tags=["players"])


@app.get("/")
async def root():
    """API health check."""
    return {
        "status": "online",
        "api": API_TITLE,
        "version": API_VERSION,
        "endpoints": [
            "/api/picks/smart",
            "/api/scores/live",
            "/api/parlays/calculate",
            "/api/performance/overview",
            "/api/players/search",
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
