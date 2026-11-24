# 文档维护 / Documentation maintenance

用户文档采用 Sphinx + MyST，`zh` 与 `en` 的规范页面使用相同小写路径。贡献与写作约定：[中文](zh/development/contributing.md) · [English](en/development/contributing.md)。

1. 构建 / Build（仓库根目录，Python 3.12）：
    ```shell
    pip install -r requirements/docs.txt
    python -m sphinx -E -a -b html -W --keep-going docs/zh /tmp/ms-agent-docs/zh
    python -m sphinx -E -a -b html -W --keep-going docs/en /tmp/ms-agent-docs/en
    ```
    更新命令参数参考 / Regenerate CLI tables: `python docs/_ext/generate_cli_reference.py`。
    共享导航与样式在 `_ext/`、`_shared/`；Logo从根目录`asset/logo.png`复制到构建输出。
    新旧链接、明暗主题、窄屏和图表应在真实浏览器中验证，不能只以构建成功代替。

2. 跨语言部署 / Cross-language deployment

    生产构建使用 `READTHEDOCS_VERSION` 作为版本键（也可在 `conf.py` 设置 `msagent_docs_version`）。官方两个 `latest` 站点默认互相链接：未设置语言清单时，按另一语言的源文件生成对应页面链接，无需额外环境变量。旧路径先归一到新页，缺少译文时禁用切换。该默认行为假定两个站点均已部署同一版文档；源码检查不代表远端构建已完成。

    Production builds use `READTHEDOCS_VERSION` as the lookup key (or set `msagent_docs_version` in `conf.py`). The two official `latest` sites link to each other by default: without a language inventory, links follow the other language's source files and need no extra environment variable. Legacy paths normalize first; missing translations disable the switch. This default assumes both sites have deployed the same documentation revision; source checks do not verify remote build completion.

    若需自定义站点地址或严格限制已发布页面，可通过 `MSAGENT_LANGUAGE_BUILDS` JSON 环境变量，或 `conf.py` 的 `msagent_language_builds`，提供目标语言基址和页面清单。显式清单会完全替代默认行为，包括 `latest`；空字典 `{}` 禁用生产环境的语言切换。例如以下配置仅允许 `latest` 的两个目标页面：

    To use custom site URLs or restrict links to confirmed published pages, supply `MSAGENT_LANGUAGE_BUILDS` as a JSON environment variable, or `msagent_language_builds` in `conf.py`, with target bases and page inventories. An explicit inventory fully replaces the default, including for `latest`; an empty dictionary `{}` disables production language links. This example allows only two target pages in `latest`:

    ```python
    msagent_language_builds = {
        'latest': {
            'en': {
                'base_url': 'https://ms-agent-en.readthedocs.io/en/latest/',
                'pages': ['index', 'core/context'],
            },
            'zh': {
                'base_url': 'https://ms-agent.readthedocs.io/zh-cn/latest/',
                'pages': ['index', 'core/context'],
            },
        },
    }
    ```

    `stable`、发布标签和分支预览仍需显式清单，各使用对应版本键与基址；只有确认对应构建完成的页面才加入清单。没有版本或页面记录时，切换禁用并显示缺失提示，不回退到 `latest`。两个 Read the Docs 项目均从 `requirements/docs.txt` 安装相同的固定文档依赖，中文索引使用 `jieba`。

    `stable`, release tags, and branch previews still require explicit inventories with their own version keys and bases. Populate them from confirmed completed builds. Missing versions/pages disable the switch with a notice, and there is no `latest` fallback. Both Read the Docs projects install the same pinned documentation dependencies from `requirements/docs.txt`; Chinese indexing uses `jieba`.

    本地预览仍用 `-D msagent_preview=1` 和同一服务根目录下的 `/zh/`、`/en/`。本地测试不验证远端版本的可用性。

    Local previews keep `-D msagent_preview=1` with `/zh/` and `/en/` under one server root. They do not verify remote build availability.

    运行 `python -m pytest tests/doc/test_site.py` 验证双语生产构建：测试设置 `READTHEDOCS_VERSION=latest` 并移除语言清单环境变量，检查实际 HTML 中的语言链接；不使用本地预览模式代替生产验证。

    Run `python -m pytest tests/doc/test_site.py` to validate both production builds. The tests set `READTHEDOCS_VERSION=latest`, remove the language inventory environment variable, and inspect language links in the generated HTML; local preview mode does not substitute for production validation.

3. doc string format

    We adopt the google style docstring format as the standard, please refer to the following documents.
    1. Google Python style guide docstring [link](http://google.github.io/styleguide/pyguide.html#381-docstrings)
    2. Google docstring example [link](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html)
    3. sample：torch.nn.modules.conv [link](https://pytorch.org/docs/stable/_modules/torch/nn/modules/conv.html#Conv1d)
    4. load function as an example：

    ```python
    def load(file, file_format=None, **kwargs):
        """Load data from json/yaml/pickle files.

        This method provides a unified api for loading data from serialized files.

        Args:
            file (str or :obj:`Path` or file-like object): Filename or a file-like
                object.
            file_format (str, optional): If not specified, the file format will be
                inferred from the file extension, otherwise use the specified one.
                Currently supported formats include "json", "yaml/yml".

        Examples:
            >>> load('/path/of/your/file')  # file is stored in disk
            >>> load('https://path/of/your/file')  # file is stored on internet
            >>> load('oss://path/of/your/file')  # file is stored in petrel

        Returns:
            The content from the file.
        """
    ```
