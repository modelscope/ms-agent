from argparse import ArgumentParser
from types import SimpleNamespace

from omegaconf import DictConfig

from ms_agent.cli.run import RunCMD


def test_run_parser_accepts_output_dir():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()
    RunCMD.define_args(subparsers)

    args = parser.parse_args(['run', '--output_dir', 'output03'])

    assert args.output_dir == 'output03'


def test_run_output_dir_cli_override_adds_missing_field():
    config = DictConfig({'llm': {'service': 'openai', 'model': 'gpt'}})
    args = SimpleNamespace(output_dir='output03')

    result = RunCMD._apply_cli_overrides(config, args)

    assert result.output_dir == 'output03'


def test_run_output_dir_cli_override_wins_over_config():
    config = DictConfig({
        'output_dir': 'from-yaml',
        'llm': {
            'service': 'openai',
            'model': 'gpt',
        },
    })
    args = SimpleNamespace(output_dir='from-cli')

    result = RunCMD._apply_cli_overrides(config, args)

    assert result.output_dir == 'from-cli'
