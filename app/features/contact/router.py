from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.core.dependencies import DbSession
from app.features.contact.notifier import ContactNotifier
from app.features.contact.schemas import ContactSubmissionCreate, ContactSubmissionResponse
from app.features.contact.service import ContactService
from app.shared.notifications import get_telegram_backend
from app.shared.rate_limit import check_rate_limit

public_router = APIRouter(prefix="/public/contact", tags=["public"])

# 5 submissions per minute per IP. The endpoint is unauthenticated, so
# the IP is the only practical key. Manager raises if Redis is up and
# someone is hammering us — the rate-limit module degrades to allow-all
# if Redis is down, so the API stays open during broker incidents.
_RATE_LIMIT = 5
_RATE_WINDOW = 60


def _client_ip(request: Request) -> str | None:
    # Same logic as the request-logging middleware; duplicated here so
    # the rate limiter doesn't have to dig into middleware internals.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


@public_router.post(
    "",
    response_model=ContactSubmissionResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_contact(
    payload: ContactSubmissionCreate,
    request: Request,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> ContactSubmissionResponse:
    ip = _client_ip(request)
    if ip:
        ok = await check_rate_limit(
            key=f"ratelimit:contact:{ip}",
            limit=_RATE_LIMIT,
            window_seconds=_RATE_WINDOW,
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

    submission = await ContactService(db).submit(
        payload,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
    )

    # Fire-and-forget Telegram notify. The submission is durable in the
    # DB before this runs, so a broker failure can't lose the lead.
    notifier = ContactNotifier(telegram=get_telegram_backend())
    background_tasks.add_task(notifier.send, submission)

    return ContactSubmissionResponse(status="ok")
