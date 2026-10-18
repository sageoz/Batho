# batho-plugin-sdk

Pluggable plugin service module for the [Batho](https://batho.sageoz.org)
engine: pipeline stage hooks, precompiled data plugins, the PluginHost
dispatcher, and the YAML rule engine (`bsg-plugin.v2`).

The engine owns algorithms and identity (parsing, resolution, entity IDs);
the SDK owns the knowledge (language packs, pruning policy, classification,
enrichment rules). See `PLUGIN_ARCHITECTURE_SPEC.md` in the engine repository.

```python
from batho_plugin import PluginHost, Stage, load_host

host = load_host()
results = host.dispatch(Stage.ON_POST_ENTITIES, ctx)
builtins = host.get_set("builtins", language="python")
```

Ships two packs as submodules:

- `batho_plugin.core` — foundation pack (mandatory, auto-loaded)
- `batho_plugin.external` — optional pack (config-gated)
