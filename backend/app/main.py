from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.comments.routes import router as comments_router
from app.config import settings
from app.realtime.bus import bus
from app.realtime.routes import router as realtime_router
from app.tasks.routes import tasks_router, workspace_tasks_router
from app.workspaces.routes import router as workspaces_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Subscribe to Redis so events published by any instance reach this one's sockets.
    await bus.start()
    yield
    await bus.stop()


app = FastAPI(title="CollabSpace API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(workspace_tasks_router)
app.include_router(tasks_router)
app.include_router(comments_router)
app.include_router(realtime_router)


@app.get("/health")
def health():
    return {"status": "ok"}
