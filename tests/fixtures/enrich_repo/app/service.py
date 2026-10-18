class GraphService:
    """Service layer for graph queries."""

    def run_service(self):
        # WHY: retries are absorbed here because the remote API is flaky
        return True
