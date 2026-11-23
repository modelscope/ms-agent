"""从实际 argparse 定义生成双语 CLI 参数表，不执行任何命令。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ms_agent.cli import cli

CLASSES = (cli.RunCMD, cli.TuiCMD, cli.UICMD, cli.AppCMD, cli.CronCMD,
           cli.AgentCMD, cli.PluginCMD, cli.ACPCmd, cli.ACPProxyCmd,
           cli.ACPRegistryCmd, cli.A2ACmd, cli.A2ARegistryCmd)


def escape(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ')


def tables(parser, command, zh):
    result = ['## `' + command + '`', '']
    result += ['| 参数 | 默认值 | 说明（来自CLI定义） |' if zh else '| Argument | Default | Description from CLI |', '| --- | --- | --- |']
    subs = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subs.extend(action.choices.items())
            continue
        if action.dest == 'help':
            continue
        name = ', '.join(action.option_strings) or action.dest
        default = action.default
        if action.required:
            default = '必填' if zh else 'required'
        elif default is None or default == argparse.SUPPRESS:
            default = '—'
        description = action.help or ('见命令用途' if zh else 'See command purpose')
        if action.choices:
            description += ' Choices: ' + ', '.join(map(str, action.choices))
        result.append(f'| `{escape(name)}` | {escape(default)} | {escape(description)} |')
    if len(result) == 4:
        result = result[:2] + [('请继续选择下列子命令。' if subs else '无额外参数。') if zh else ('Choose a subcommand below.' if subs else 'No additional arguments.')]
    result += ['']
    for name, child in subs:
        result += tables(child, command + ' ' + name, zh)
    return result


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers()
    for cls in CLASSES:
        cls.define_args(subs)
    for lang in ('zh', 'en'):
        zh = lang == 'zh'
        intro = ('# CLI 参数参考\n\n下列参数表由当前源码的argparse定义生成，保留CLI原始帮助文字，避免手写默认值漂移。用 `ms-agent <command> --help` 查本机版本。操作教程见[CLI任务](../user-guide/cli.md)。\n\n'
                 '## 阅读约定\n\n- 表中默认值是参数解析器默认值，不等于全部有效Agent配置。\n- `run --trust_remote_code true` 与 `tui --trust_remote_code` 语法不同。\n- 未知 `--a.b value` 可被任务配置层解析；并非每个管理命令都支持。\n- `run --mcp_server_file`是文档推荐的MCP文件入口，不能仅凭参数被声明认定其他兼容选项已接入。\n- 凭据使用环境变量或私有dotenv；避免将Key保留在命令历史。\n\n' if zh else
                 '# CLI reference\n\nThese tables are generated from current argparse definitions, retaining CLI help text to avoid drifting defaults. Use `ms-agent <command> --help` for your installed version. See [CLI tasks](../user-guide/cli.md) for procedures.\n\n'
                 '## Reading the tables\n\n- Defaults belong to argument parsing, not the entire effective agent configuration.\n- `run --trust_remote_code true` differs from the boolean `tui --trust_remote_code` flag.\n- Extra `--a.b value` arguments can reach task configuration; not every management command accepts them.\n- Prefer `run --mcp_server_file` for MCP files; declaration alone does not prove another compatibility option is connected.\n- Keep keys in environment/private dotenv, not shell history.\n\n')
        body = []
        for name, child in subs.choices.items():
            body += tables(child, 'ms-agent ' + name, zh)
        (ROOT / f'docs/{lang}/development/cli-reference.md').write_text((intro + '\n'.join(body)).rstrip() + '\n')


if __name__ == '__main__':
    main()
