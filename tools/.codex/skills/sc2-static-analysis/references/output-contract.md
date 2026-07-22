# Static Analysis Output Contract

Store outputs under the active stage:

```text
evidence/static/
  dependency-graph.json
  analyzer-commands.json
  unresolved.json
```

Each node needs a stable ID, kind, source path, and relevant metadata. Each edge needs source, target,
relation, and one or more evidence references.

Do not flatten these distinct relations into a generic dependency:

- declared document dependency;
- Galaxy include;
- function call;
- Catalog definition or override;
- trigger registration;
- initializer activation;
- Bank read or write;
- objective or reward activation.

The unresolved list must state whether static, runtime, or manual evidence is required next.
