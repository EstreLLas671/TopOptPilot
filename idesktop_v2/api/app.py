"""Compose TopOptPilot research and engineering desktop routes."""

from contextlib import asynccontextmanager

from topoptpilot.api.fastapi_app import app

from idesktop_v2 import __version__
from idesktop_v2.assistant.router import router as engineering_assistant_router
from idesktop_v2.conversations import cleanup_empty_test_conversations_once, router as conversation_router
from idesktop_v2.engineering.router import router as engineering_router
from idesktop_v2.research_router import router as research_artifact_router, settings_router as research_settings_router
from idesktop_v2.engineering.environment_discovery import initialize_engineering_discovery


_topoptpilot_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _idesktop_lifespan(application):
    initialize_engineering_discovery()
    cleanup_empty_test_conversations_once()
    async with _topoptpilot_lifespan(application):
        yield


app.router.lifespan_context = _idesktop_lifespan

app.title = "TopOptPilot Sidecar API"
app.version = __version__
app.description = "Unified engineering and policy-controlled research desktop API."
app.include_router(engineering_router)
app.include_router(engineering_assistant_router)
app.include_router(conversation_router)
app.include_router(research_artifact_router)
app.include_router(research_settings_router)
