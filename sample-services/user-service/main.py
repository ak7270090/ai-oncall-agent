import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from settings import get_settings


class User(BaseModel):
    id: int
    name: str
    email: str


USERS = {
    user.id: user
    for user in (
        User(id=1, name="Asha Rao", email="asha@example.com"),
        User(id=2, name="Ben Ortiz", email="ben@example.com"),
        User(id=3, name="Chen Li", email="chen@example.com"),
    )
}

settings = get_settings()
app = FastAPI(title=settings.service_name, version=settings.app_version)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int) -> User:
    if user_id not in USERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id} not found")
    return USERS[user_id]


if __name__ == "__main__":
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
