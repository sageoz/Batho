import { useGraphEntity } from "../hooks/useGraph";

export function GraphPanel(props: { id: string }): object {
    const entity = useGraphEntity(props.id);
    return entity;
}
