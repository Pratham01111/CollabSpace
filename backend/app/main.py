from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.tasks.routes import tasks_router, workspace_tasks_router
from app.workspaces.routes import router as workspaces_router

app = FastAPI(title="CollabSpace API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(workspace_tasks_router)
app.include_router(tasks_router)


@app.get("/health")
def health():
    return {"status": "ok"}
