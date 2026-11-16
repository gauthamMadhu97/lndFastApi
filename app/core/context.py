from contextvars import ContextVar

# Set by the request middleware so logs and error bodies can include it.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return request_id_ctx.get()
