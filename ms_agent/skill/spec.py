# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from dataclasses import dataclass

from .prompts import DEFAULT_IMPLEMENTATION, DEFAULT_PLAN, DEFAULT_TASKS


@dataclass
class Spec:
    """
    Specification for an AI agent's task planning and execution.
    """

    plan: str

    tasks: str

    implementation: str = ''

    def __post_init__(self):

        if not self.plan:
            self.plan = DEFAULT_PLAN

        if not self.tasks:
            self.tasks = DEFAULT_TASKS

        if not self.implementation:
            self.implementation = DEFAULT_IMPLEMENTATION

    def dump(self, output_dir: str) -> str:
        """
        Dump the spec to the specified output directory.

        Args:
            output_dir (str): The directory to dump the spec files.

        Returns:
            str: The path to the dumped spec directory.
        """
        output_path: str = os.path.join(output_dir, '.spec')
        os.makedirs(output_path, exist_ok=True)

        with open(
                os.path.join(output_path, 'plan.md'), 'w',
                encoding='utf-8') as f:
            f.write(self.plan)

        with open(
                os.path.join(output_path, 'tasks.md'), 'w',
                encoding='utf-8') as f:
            f.write(self.tasks)

        with open(
                os.path.join(output_path, 'implementation.md'),
                'w',
                encoding='utf-8') as f:
            f.write(self.implementation)

        return output_path


if __name__ == '__main__':
    spec = Spec(plan='', tasks='')
    print('Plan:', spec.plan)
    print('Tasks:', spec.tasks)
    print('Implementation:', spec.implementation)
