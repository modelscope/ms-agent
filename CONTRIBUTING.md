<!---
Copyright (c) Alibaba, Inc. and its affiliates.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Contribute to MS-Agent

We sincerely appreciate every contribution, regardless of its form. While contributing code is certainly impactful,
there are many other ways to aid the community.
Providing answers to questions, extending a helping hand to peers, and enhancing the documentation are just as essential
to our collective success.


Your support doesn't go unnoticed when you share your experiences.
Mention our library in your blog posts about the phenomenal projects you've built with its help, give us a shoutout on
Twitter or WeChat, whenever our library comes to your rescue,
or simply give the repository a star as a token of your appreciation.

However, you choose to contribute, please be mindful and respect our
[code of conduct](https://github.com/modelscope/MS-Agent/blob/master/CODE_OF_CONDUCT.md).


## Ways to contribute

There are several ways you can contribute to MS-Agent:

* Fix outstanding issues with the existing code, found them at [here](https://github.com/modelscope/MS-Agent/issues).
* Submit issues related to bugs or desired new features [here](https://github.com/modelscope/MS-Agent/issues/new/choose)
* Implement new tools, please refer the doc [here](https://github.com/modelscope/MS-Agent/tree/master/docs/contributing/tool_contribution_guide.md)
* Contribute to the examples or to the documentation, [here](https://github.com/modelscope/MS-Agent/tree/master/examples)

> All contributions are equally valuable to the community.

## Styles

MS-Agent follow the same styles as the Modelscope project. Please find detail at [here](https://github.com/modelscope/MS-Agent/blob/master/.pre-commit-config.yaml)
Please make sure follow the following steps to install the pre-commit hooks:

```shell
# for the first time please run the following command to install pre-commit hooks
pip install pre-commit
pre-commit install
pre-commit run --all-files

# In the rest of the time, you could just run normal git commit to activate lint revised
git add .
git commit -m "add new tool"
# if you want to skip the lint check, you could use the following command
git commit -m "add new tool" --no-verify
```
