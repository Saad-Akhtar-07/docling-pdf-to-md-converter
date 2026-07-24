from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import documents, health, plans
from apps.api.settings import get_settings
from slidevision.extraction.office import start_libreoffice_listener, stop_libreoffice_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Best-effort: convert_office_to_pdf() falls back to a one-shot
    # conversion per file if no listener is running, so a missing
    # LibreOffice install here doesn't stop the API from starting.
    start_libreoffice_listener()
    yield
    stop_libreoffice_listener()


app = FastAPI(title="SlideVision API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(plans.router)
