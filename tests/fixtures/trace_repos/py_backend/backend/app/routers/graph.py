from app.deps import get_graph_service
from app.schemas.graph import validate_entity_payload, validate_query_payload
from app.services.graph_service import GraphService


def Depends(f):
    return f()


def endpoint_get_entity(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.get_entity("x")


def endpoint_list_entities(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.list_entities()


def endpoint_query(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.query_graph("q")


def endpoint_file_graph(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.get_file_graph("f.py")


def endpoint_overview(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.overview_stats()


def endpoint_resolve(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.resolve_repo("n")


def endpoint_delete(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.delete_repo("n")


def endpoint_export(graph_svc: GraphService = Depends(get_graph_service)):
    return graph_svc.export_graph("out")


def endpoint_create(payload: dict, graph_svc: GraphService = Depends(get_graph_service)):
    data = validate_entity_payload(payload)
    return graph_svc.resolve_repo(data["name"])


def endpoint_search(payload: dict, graph_svc: GraphService = Depends(get_graph_service)):
    if validate_query_payload(payload):
        return graph_svc.query_graph(payload["q"])
    return {}
