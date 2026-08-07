from fastapi import FastAPI

from repooperator_worker.api.routes import router
from repooperator_worker.services.event_service import reap_orphaned_runs


def create_app() -> FastAPI:
    app = FastAPI(
        title="RepoOperator Local Worker",
        version="0.1.0",
        description="Local repository and command worker for RepoOperator.",
    )
    app.include_router(router)

    @app.on_event("startup")
    def _reap_orphaned_runs() -> None:
        # Runs marked running/cancelling/pending belong to a previous worker
        # process and can never finish — left alone they spin "Run active"
        # indicators in the UI forever.
        reap_orphaned_runs()

    return app


app = create_app()
