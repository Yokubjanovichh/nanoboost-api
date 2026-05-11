from fastapi import APIRouter

from app.features.auth.router import router as auth_router
from app.features.clients.router import router as clients_router
from app.features.dashboard.router import router as dashboard_router
from app.features.games.router import public_router as games_public_router
from app.features.games.router import router as games_router
from app.features.orders.public_router import public_router as orders_public_router
from app.features.orders.router import router as orders_router
from app.features.reviews.router import public_router as reviews_public_router
from app.features.reviews.router import router as reviews_router
from app.features.services.router import public_router as services_public_router
from app.features.services.router import router as services_router
from app.features.users.router import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(games_router)
api_router.include_router(services_router)
api_router.include_router(clients_router)
api_router.include_router(orders_router)
api_router.include_router(reviews_router)
api_router.include_router(dashboard_router)
api_router.include_router(games_public_router)
api_router.include_router(services_public_router)
api_router.include_router(reviews_public_router)
api_router.include_router(orders_public_router)
