import argparse

from ms_agent.cli.run import RunCMD


def run_cmd():
    parser = argparse.ArgumentParser(
        'ModelScope-agent Command Line tool',
        usage='ms-agent <command> [<args>]')

    subparsers = parser.add_subparsers(
        help='ModelScope-agent commands helpers')

    RunCMD.define_args(subparsers)

    args = parser.parse_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        exit(1)
    cmd = args.func(args)
    cmd.execute()


if __name__ == '__main__':
    run_cmd()
