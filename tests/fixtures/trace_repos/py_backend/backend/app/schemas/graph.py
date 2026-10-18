from app.services.repo_registry import check_name, normalize_name


def validate_entity_payload(payload: dict) -> dict:
    return {"name": normalize_name(payload.get("name", ""))}


def validate_query_payload(payload: dict) -> bool:
    return check_name(payload.get("q", ""))
