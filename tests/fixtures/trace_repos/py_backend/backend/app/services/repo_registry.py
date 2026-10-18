_REGISTRY: dict = {}


def register_repo(name: str) -> dict:
    _REGISTRY[name] = {"name": name}
    return _REGISTRY[name]


def lookup_repo(name: str) -> dict:
    return _REGISTRY.get(name, {})


def remove_repo(name: str) -> dict:
    return _REGISTRY.pop(name, {})


def count_repos() -> int:
    return len(_REGISTRY)


def normalize_name(name: str) -> str:
    return name.strip().lower()


def check_name(name: str) -> bool:
    return bool(normalize_name(name))
