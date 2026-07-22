# Adapter Boundaries

Valid dependency direction:

```text
official/external data
  -> shared runtime
  -> commander mod
  -> series adapter
  -> map adapter
  -> commander-map adapter
  -> map
```

Adapters must not:

- become a second canonical commander implementation;
- copy large sections of the map or commander mod;
- depend on unrelated map families;
- hide missing source dependencies;
- mutate external repositories;
- use runtime patching when a stable Catalog or dependency solution exists.

Prefer explicit composition manifests over launcher-time file injection. Runtime injection requires a
documented reason and dynamic regression coverage.
