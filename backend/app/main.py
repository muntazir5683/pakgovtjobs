import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, sources_registry
from .api import router
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request is too noisy
log = logging.getLogger("pakgovjobs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_serverless:
        # Vercel: no scheduler, no startup work. Tables are created lazily by db.ensure_ready() on the first
        # request, and the crawler (which also syncs sources.json) runs from GitHub Actions.
        try:
            yield
        finally:
            db.close_pool()
        return

    if settings.admin_password == "change-me" or settings.admin_token_secret == "change-me-too":
        log.warning("ADMIN_PASSWORD / ADMIN_TOKEN_SECRET still have default values - set them in backend/.env")
    db.init_schema()
    n = sources_registry.sync_sources()
    log.info("Synced %s sources from %s", n, settings.sources_file.name)
    scheduler = None
    if settings.run_scheduler:
        from . import scheduler  # imports the crawler stack (bs4, httpx, ...) - only needed when scheduling

        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()
        db.close_pool()


app = FastAPI(title="PakGovJobs API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)
