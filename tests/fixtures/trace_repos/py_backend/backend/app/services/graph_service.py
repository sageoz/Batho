from app.services.repo_registry import (
    count_repos,
    lookup_repo,
    normalize_name,
    register_repo,
    remove_repo,
)


class GraphService:
    """First-party service used by the router layer."""

    def get_entity(self, entity_id: str) -> dict:
        return lookup_repo(entity_id)

    def list_entities(self) -> int:
        return count_repos()

    def query_graph(self, name: str) -> dict:
        return register_repo(name)

    def delete_repo(self, name: str) -> dict:
        return remove_repo(name)

    def get_file_graph(self, file_path: str) -> dict:
        return {"file": file_path}

    def overview_stats(self) -> dict:
        return {"entities": 0}

    def resolve_repo(self, name: str) -> str:
        return normalize_name(name)

    def export_graph(self, out: str) -> str:
        return out
