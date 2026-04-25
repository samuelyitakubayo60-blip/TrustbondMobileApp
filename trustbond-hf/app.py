"""
TrustBond Backend on Hugging Face Spaces
Backend-only deployment (Frontend on Vercel)
"""

from fastapi import FastAPI
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

# Import your existing backend
try:
    from app.main import app as backend_app
    print("✅ TrustBond backend loaded successfully")
except Exception as e:
    print(f"❌ Backend loading failed: {e}")
    backend_app = FastAPI()

# Use backend app directly (no frontend mounting)
app = backend_app

# Add health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "trustbond-backend",
        "frontend": "Deployed on Vercel",
        "ml_models": "GPU Enabled",
        "features": "Evidence Analysis, Hotspot Detection, YOLO Models"
    }

@app.get("/")
async def root():
    return {
        "message": "TrustBond Backend API is running",
        "docs": "/docs",
        "redoc": "/redoc", 
        "api": "/api/v1/",
        "frontend": "https://your-vercel-app.vercel.app",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
