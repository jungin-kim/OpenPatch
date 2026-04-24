from fastapi import FastAPI

from openpatch_worker.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenPatch Local Worker",
        version="0.1.0",
        description="Local repository and command worker for OpenPatch.",
    )
    app.include_router(router)
    return app


app = create_app()
