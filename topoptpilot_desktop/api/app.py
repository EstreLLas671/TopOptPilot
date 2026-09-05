"""Compose TopOptPilot research and engineering desktop routes."""

from contextlib import asynccontextmanager

from topoptpilot.api.fastapi_app import app

from topoptpilot_desktop import __version__
from topoptpilot_desktop.assistant.router import router as engineering_assistant_router
from topoptpilot_desktop.conversations import cleanup_empty_test_conversations_once, router as conversation_router
from topoptpilot_desktop.engineering.router import router as engineering_router
from topoptpilot_desktop.headless_router import router as headless_router
from topoptpilot_desktop.demo_router import router as demo_router
from topoptpilot_desktop.research_router import router as research_artifact_router, settings_router as research_settings_router
from topoptpilot_desktop.engineering.environment_discovery import initialize_engineering_discovery


_research_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _topoptpilot_lifespan(application):
    initialize_engineering_discovery()
    cleanup_empty_test_conversations_once()
    async with _research_lifespan(application):
        yield


app.router.lifespan_context = _topoptpilot_lifespan

app.title = "TopOptPilot Sidecar API"
app.version = __version__
app.description = "Unified engineering and policy-controlled research desktop API."
app.include_router(engineering_router)
app.include_router(engineering_assistant_router)
app.include_router(conversation_router)
app.include_router(research_artifact_router)
app.include_router(research_settings_router)
app.include_router(headless_router)
app.include_router(demo_router)
