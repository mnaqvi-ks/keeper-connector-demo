"""Azure Functions middleware for the Keeper Secrets Manager custom connector.

Security invariant: no secret value (login, password, url value, notes body)
is ever passed to `logger`.
Only non-sensitive identifiers (uid, folder_uid, title, record counts) appear
in logs. `logger.exception` is used only inside `except` blocks so that the
traceback comes from the Keeper SDK or Azure Functions runtime, never from a
user-provided payload.
"""

import functools
import json
import logging
import os
import threading
import time
from collections import Counter, deque
from http import HTTPStatus
from typing import Any, Callable

import azure.functions as func
from keeper_secrets_manager_core import SecretsManager
from keeper_secrets_manager_core.storage import InMemoryKeyValueStorage
from keeper_secrets_manager_core.dto.dtos import RecordCreate, RecordField

logger = logging.getLogger(__name__)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

JsonBody = dict[str, Any]

MAX_TITLE_LENGTH = 1000
MAX_STRING_FIELD_LENGTH = 10000

# Best-effort in-memory rate limiting.
# NOTE: This is per Function worker process. It resets on cold start and does not
# enforce a strict global quota under scale-out.
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60

# Fields validated on POST /secrets; keep in sync with CreateSecretRequest in the swagger.
_CREATE_STRING_FIELDS: tuple[str, ...] = (
    "title", "login", "password", "url", "notes",
)
# Fields accepted by PUT /secrets/{uid}; keep in sync with UpdateSecretRequest in the swagger.
_UPDATE_STRING_FIELDS: tuple[str, ...] = (
    "title", "login", "password", "url", "notes",
)

_rate_limit_lock = threading.Lock()
_rate_limit_buckets: dict[str, deque[float]] = {}


def _get_functions_key(req: func.HttpRequest) -> str:
    # Azure Functions uses header `x-functions-key`. Headers may be passed with
    # different casing by clients.
    return (
        req.headers.get("x-functions-key")
        or req.headers.get("X-Functions-Key")
        or ""
    )


def _rate_limit_check(req: func.HttpRequest) -> func.HttpResponse | None:
    """Return 429 response if the caller exceeds the rate limit."""
    key = _get_functions_key(req)
    now = time.monotonic()

    with _rate_limit_lock:
        bucket = _rate_limit_buckets.get(key)
        if bucket is None:
            bucket = deque()
            _rate_limit_buckets[key] = bucket

        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT_REQUESTS:
            retry_after = max(
                1,
                int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0]) + 0.9999),
            )
            payload = {
                "error": "Rate limit exceeded",
                "retry_after_seconds": retry_after,
            }
            return func.HttpResponse(
                json.dumps(payload),
                mimetype="application/json",
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return None


@functools.lru_cache(maxsize=1)
def _resolve_ksm_config() -> str:
    """Resolve the Base64-encoded KSM config from Azure Key Vault reference."""
    config = (os.environ.get("KSM_CONFIG") or "").strip()
    if not config:
        raise ValueError(
            "KSM_CONFIG environment variable is not set. "
            "Ensure the Key Vault reference is configured in Azure App Settings."
        )
    logger.info("KSM config resolved successfully.")
    return config


@functools.lru_cache(maxsize=1)
def get_ksm_client() -> SecretsManager:
    """Return a cached Keeper SDK client for the lifetime of the Function worker.

    Azure Functions recycles the worker (and therefore this cache) on cold start
    or when App Settings change, so config rotation is handled automatically
    without manual cache invalidation.
    """
    config = _resolve_ksm_config()
    storage = InMemoryKeyValueStorage(config)
    return SecretsManager(config=storage)


def _folders_as_dicts(
    client: SecretsManager, include_record_counts: bool = False
) -> list[dict[str, Any]]:
    """Return folder list as dicts with optional record counts."""
    folders = client.get_folders()
    counts_by_folder: Counter = Counter()
    if include_record_counts:
        for r in client.get_secrets():
            fid = getattr(r, "folder_uid", None) or ""
            if fid:
                counts_by_folder[fid] += 1

    results: list[dict[str, Any]] = []
    for f in folders:
        uid = getattr(f, "folder_uid", None) or getattr(f, "uid", "")
        name = getattr(f, "name", "")
        parent_uid = getattr(f, "parent_uid", "")
        row: dict[str, Any] = {"uid": uid, "name": name, "parent_uid": parent_uid}
        if include_record_counts:
            row["total_records"] = counts_by_folder.get(uid, 0)
        results.append(row)
    return results


def _valid_folder_uids(client: SecretsManager) -> set[str]:
    """Return the set of accessible folder UIDs."""
    return {
        f["uid"]
        for f in _folders_as_dicts(client)
        if f.get("uid")
    }


def _serialize_secret_record(record: Any) -> dict[str, Any]:
    """Build a flat response payload from any record type.

    Iterates ALL fields from the SDK record and flattens them as top-level
    keys so login, SSH, BankCard, and every other record type are returned
    with their full field data.
    """
    data: dict[str, Any] = getattr(record, "dict", {}) or {}
    raw_fields: list[dict[str, Any]] = data.get("fields", [])
    custom_fields: list[dict[str, Any]] = data.get("custom", [])

    result: dict[str, Any] = {
        "uid": record.uid,
        "title": record.title,
        "type": record.type,
        "notes": data.get("notes", ""),
        "folder_uid": getattr(record, "folder_uid", ""),
        "is_editable": getattr(record, "is_editable", False),
    }

    for f in raw_fields:
        field_type = f.get("type", "")
        values = f.get("value", [])
        if not field_type:
            continue
        result[field_type] = values[0] if len(values) == 1 else values

    result["custom"] = [
        {"type": c.get("type", ""), "label": c.get("label", ""), "value": c.get("value", [])}
        for c in custom_fields
    ]

    return result


def _json_response(
    body: dict | list, status_code: int = HTTPStatus.OK
) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body),
        mimetype="application/json",
        status_code=status_code,
    )


def _error_response(
    message: str,
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR,
    **extra: Any,
) -> func.HttpResponse:
    payload = {"error": message, **extra}
    return _json_response(payload, status_code)


def _parse_json_body(
    req: func.HttpRequest,
) -> tuple[JsonBody | None, func.HttpResponse | None]:
    """Parse and validate a JSON request body with Content-Type check."""
    content_type = req.headers.get("Content-Type", "").lower()
    if "application/json" not in content_type:
        return None, _error_response(
            "Content-Type must be application/json",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    try:
        body = req.get_json()
    except (ValueError, json.JSONDecodeError):
        return None, _error_response(
            "Invalid JSON in request body", HTTPStatus.BAD_REQUEST
        )
    if not isinstance(body, dict):
        return None, _error_response(
            "Request body must be a JSON object", HTTPStatus.BAD_REQUEST
        )
    return body, None


def _validate_uid(uid_value: str | None) -> tuple[str | None, func.HttpResponse | None]:
    """Validate that a UID path parameter is present and non-empty."""
    if uid_value is None or not str(uid_value).strip():
        return None, _error_response("uid is required", HTTPStatus.BAD_REQUEST)
    return str(uid_value).strip(), None


def _require_string(
    body: JsonBody, name: str
) -> tuple[str | None, func.HttpResponse | None]:
    """Validate that `body[name]` is a present, non-empty string. Returns the stripped value."""
    raw = body.get(name)
    if raw is None:
        return None, _error_response(f"{name} is required", HTTPStatus.BAD_REQUEST)
    if not isinstance(raw, str):
        return None, _error_response(
            f"{name} must be a string", HTTPStatus.BAD_REQUEST
        )
    if not raw.strip():
        return None, _error_response(
            f"{name} must not be blank (whitespace-only values are not allowed)",
            HTTPStatus.BAD_REQUEST,
        )
    return raw.strip(), None


def _validate_string_fields(fields: JsonBody) -> func.HttpResponse | None:
    """Return a 400 error response if any field is non-string or exceeds its length limit."""
    for name, value in fields.items():
        if value is None:
            continue
        if not isinstance(value, str):
            return _error_response(
                f"{name} must be a string", HTTPStatus.BAD_REQUEST
            )
        limit = MAX_TITLE_LENGTH if name == "title" else MAX_STRING_FIELD_LENGTH
        if len(value) > limit:
            return _error_response(
                f"{name} exceeds {limit} characters", HTTPStatus.BAD_REQUEST
            )
    return None


def _endpoint(route_name: str, failure_message: str) -> Callable:
    """Combined decorator: enforces rate limit, then catches KSM errors.

    `ValueError` is reserved for KSM configuration problems surfaced by
    `_resolve_ksm_config`; everything else is treated as an unexpected backend
    failure and returns a generic 500 so secret values are never echoed back to
    the caller.
    """
    def decorator(
        fn: Callable[..., func.HttpResponse],
    ) -> Callable[..., func.HttpResponse]:
        @functools.wraps(fn)
        def wrapper(req: func.HttpRequest, *args: Any, **kwargs: Any) -> func.HttpResponse:
            rl = _rate_limit_check(req)
            if rl is not None:
                return rl
            try:
                return fn(req, *args, **kwargs)
            except ValueError:
                logger.exception("KSM configuration error in %s.", route_name)
                return _error_response("Configuration error")
            except Exception:
                logger.exception("%s failed.", route_name)
                return _error_response(failure_message)
        return wrapper
    return decorator


# --- HEALTH CHECK ---
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json_response({"status": "ok"})


# --- 1. LIST ALL SECRETS ---
@app.route(route="secrets", methods=["GET"])
@_endpoint("list_secrets", "Failed to list secrets")
def list_secrets(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Fetching all secrets.")
    client = get_ksm_client()
    records = client.get_secrets()
    logger.info("Retrieved %d secret(s).", len(records))
    results = [
        {
            "uid": r.uid,
            "title": r.title,
            "type": r.type,
            "folder_uid": r.folder_uid,
        }
        for r in records
    ]
    return _json_response(results)


# --- 2. GET SECRET DETAILS ---
@app.route(route="secrets/{uid}", methods=["GET"])
@_endpoint("get_secret", "Failed to fetch secret")
def get_secret(req: func.HttpRequest) -> func.HttpResponse:
    uid, err = _validate_uid(req.route_params.get("uid"))
    if err:
        return err
    logger.info("Fetching secret %s", uid)
    client = get_ksm_client()
    records = client.get_secrets([uid])

    if not records:
        return _error_response("Secret not found", HTTPStatus.NOT_FOUND, uid=uid)

    return _json_response(_serialize_secret_record(records[0]))


# --- 3. LIST ALL FOLDERS ---
@app.route(route="folders", methods=["GET"])
@_endpoint("list_folders", "Failed to list folders")
def list_folders(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Fetching all folders.")
    client = get_ksm_client()
    results = _folders_as_dicts(client, include_record_counts=True)
    logger.info("Retrieved %d folder(s).", len(results))
    return _json_response(results)


# --- 4. CREATE SECRET ---
@app.route(route="secrets", methods=["POST"])
@_endpoint("create_secret", "Failed to create secret")
def create_secret(req: func.HttpRequest) -> func.HttpResponse:
    body, err = _parse_json_body(req)
    if err:
        return err

    folder_uid, err = _require_string(body, "folder_uid")
    if err:
        return err

    client = get_ksm_client()
    allowed = _valid_folder_uids(client)
    if folder_uid not in allowed:
        return _error_response(
            "folder_uid is not an accessible folder for this application",
            HTTPStatus.BAD_REQUEST,
            folder_uid=folder_uid,
        )

    title, err = _require_string(body, "title")
    if err:
        return err

    field_err = _validate_string_fields({
        name: body[name] for name in _CREATE_STRING_FIELDS if name in body
    })
    if field_err:
        return field_err

    login = body.get("login", "")
    password = body.get("password", "")
    url = body.get("url", "")
    notes = body.get("notes", "")

    record = RecordCreate(record_type="login", title=title)
    record.notes = notes
    record.folder_uid = folder_uid
    record.fields = [
        RecordField(field_type="login", value=[login]),
        RecordField(field_type="password", value=[password]),
        RecordField(field_type="url", value=[url]),
    ]

    logger.info("Creating record '%s' in folder '%s'.", title, folder_uid)
    response = client.create_secret(folder_uid, record)
    if not response:
        logger.error(
            "create_secret returned empty uid for title=%r folder_uid=%s",
            title, folder_uid,
        )
        return _error_response("Secret creation did not return a UID")

    return _json_response(
        {
            "message": "Secret created successfully",
            "title": title,
            "folder_uid": folder_uid,
            "response": str(response),
        },
        HTTPStatus.CREATED,
    )


# --- 5. UPDATE SECRET ---
@app.route(route="secrets/{uid}", methods=["PUT"])
@_endpoint("update_secret", "Failed to update secret")
def update_secret(req: func.HttpRequest) -> func.HttpResponse:
    uid, err = _validate_uid(req.route_params.get("uid"))
    if err:
        return err
    body, err = _parse_json_body(req)
    if err:
        return err
    if not body:
        return _error_response(
            "Request body must include at least one field to update",
            HTTPStatus.BAD_REQUEST,
        )

    field_err = _validate_string_fields({
        name: body[name] for name in _UPDATE_STRING_FIELDS if name in body
    })
    if field_err:
        return field_err

    client = get_ksm_client()

    records = client.get_secrets([uid])
    if not records:
        return _error_response("Secret not found", HTTPStatus.NOT_FOUND, uid=uid)

    record = records[0]

    if "title" in body:
        record.title = body["title"]
    if "notes" in body:
        record.dict["notes"] = body["notes"]

    for field_type in ("login", "password", "url"):
        if field_type in body:
            record.field(field_type, value=body[field_type])

    # Rebuild raw_json from dict so save() picks up ALL changes
    # (e.g. notes set via record.dict).
    record._update()
    client.save(record)
    logger.info("Secret %s updated.", uid)

    return _json_response({"message": f"Secret {uid} updated successfully"})
