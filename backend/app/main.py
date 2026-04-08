"""FastAPI application entrypoint for the Job Discovery Engine."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Job Discovery Engine",
    description="AI-assisted job discovery with verified results",
    version="0.1.0",
)

# Allow React frontend to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Job Discovery Engine API", "version": "0.1.0"}
