import { getEntity, listEntities, queryGraph } from "../lib/apiClient";

export function useGraphEntity(id: string): object {
    return getEntity(id);
}

export function useGraphList(): object[] {
    return listEntities();
}

export function useGraphQuery(q: string): object {
    return queryGraph(q);
}
