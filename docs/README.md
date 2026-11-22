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

2. doc string format

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
