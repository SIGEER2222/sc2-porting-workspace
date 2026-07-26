# Static Analysis Output Contract

Store outputs under the active stage:

```text
evidence/static/
  dependency-graph.json      # 合并后的依赖图（符合 dependency-graph.schema.json）
  diagnostics.json           # Galaxy 语法/类型诊断（符合 static-diagnostics.schema.json）
  packaging-report.json      # Packaging 校验报告（符合 packaging-report.schema.json）
  analyzer-commands.json     # 执行的分析器命令列表
  unresolved.json            # 未解析依赖列表
  stage-verdict.json         # 阶段校验汇总（pass/fail）
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
