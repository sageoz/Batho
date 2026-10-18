import { useGraphList } from "../hooks/useGraph";

export function RepoList(): object[] {
    const items = useGraphList();
    return items;
}
