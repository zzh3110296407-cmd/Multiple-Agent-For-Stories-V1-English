from fastapi import HTTPException, Request


async def read_limited_request_body(
    request: Request,
    *,
    max_bytes: int,
) -> bytes:
    """Read a request body without allowing unbounded in-memory accumulation."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive.")

    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header.",
            ) from exc
        if parsed_length < 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header.",
            )
        if parsed_length > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Request body exceeds the configured size limit.",
            )

    body = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Request body exceeds the configured size limit.",
            )
        body.extend(chunk)
    return bytes(body)
