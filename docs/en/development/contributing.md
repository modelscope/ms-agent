# Contributing

Contributions include fixes, model/tool adapters, tests, and documentation. Define the problem and scope, then use existing extension points instead of duplicating SDK behavior in interfaces.

## Develop and verify

Install from source and run nearby tests in an isolated environment. Follow `setup.cfg` and pre-commit configuration; WebUI conventions live in `webui/AGENTS.md`.

```bash
pip install -e .
pytest tests/config -q
```

This example covers configuration tests only. Select tests for the changed module and cover success, failure, and cancellation. Optional services and paid models require explicit environment/budget; do not automatically use maintainers' real credentials.

## Write documentation

- Tutorials explain prerequisites, steps, results, and recovery; references define types, defaults, and scope.
- Follow current implementation, distinguishing defaults, compatibility, and proposals.
- Use matching lowercase paths in `docs/zh` and `docs/en`. Align meaning and claims rather than translating mechanically.
- Internal links include `.md`; keep migration entry points when moving pages. Do not add empty navigation placeholders.
- Use Mermaid for one mechanism per diagram and test both languages/themes and narrow screens.
- Use placeholder keys and test-project screenshots, never private data.

## Build the site

From the repository root in Python 3.12:

```bash
pip install -r requirements/docs.txt
python -m sphinx -E -a -b html -W --keep-going docs/zh /tmp/ms-agent-docs/zh
python -m sphinx -E -a -b html -W --keep-going docs/en /tmp/ms-agent-docs/en
```

`-E -a` forces fresh reading/output and `-W` treats warnings as errors. A build does not establish visual quality or valid anchors. Inspect home, tutorial, reference, and diagram pages, including copy controls, navigation, and language switching.

## Distribute extensions

Use [Plugins](../core/plugins.md) to package skills, commands, hooks, and agent definitions. Run reviewed custom Python nodes with `ms-agent run --config ./task --trust_remote_code true`.

When `--config ./task` is a directory, the CLI reads `./task/author.txt` to display contributor information. A concrete YAML-file argument does not automatically read an adjacent `author.txt`. This file affects display, not execution permissions.

## API comments and change scope

Use Google-style Python docstrings for parameters, returns, and important side effects. Test fixtures and internal debugging notes are not user guides. Update relevant module documentation and RFC status for architecture changes.

Inspect diffs, secrets, generated artifacts, and unrelated files before committing. See [repository contribution guidance](https://github.com/modelscope/ms-agent/blob/main/CONTRIBUTING.md) and [WebUI maintenance commands](https://github.com/modelscope/ms-agent/blob/main/webui/README.md).
