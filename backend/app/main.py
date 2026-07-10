from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine
from app.routers import (
    auth, schools, classes, sections, subjects, activities, resources, teachers, timetables,
    leaves, substitutions, notifications, swaps, exams, reports, assistant, bulk, assignments,
    calendar, validation, teacher_availability,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="EduFlow AI")

# Production must name its frontend origins; dev stays permissive so the static
# frontend works from file:// or any local static server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.is_production else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(schools.router)
app.include_router(classes.router)
app.include_router(sections.router)
app.include_router(subjects.router)
app.include_router(activities.router)
app.include_router(resources.router)
app.include_router(teachers.router)
app.include_router(timetables.router)
app.include_router(leaves.router)
app.include_router(substitutions.router)
app.include_router(notifications.router)
app.include_router(swaps.router)
app.include_router(exams.router)
app.include_router(reports.router)
app.include_router(assistant.router)
app.include_router(bulk.router)
app.include_router(assignments.router)
app.include_router(calendar.router)
app.include_router(validation.router)
app.include_router(teacher_availability.router)



@app.get("/health")
def health():
    return {"status": "ok"}


# Serve the static admin console from the API origin so the browser needs no CORS.
# Mounted last and under a prefix so it can never shadow an API route.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
