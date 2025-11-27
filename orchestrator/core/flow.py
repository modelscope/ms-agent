import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger('Orchestrator')


class FlowController:
    """
    流程控制器。
    负责处理 Human-in-the-Loop (HITL) 交互，如暂停、等待用户审查文件等。
    """

    def __init__(self, workspace_manager):
        self.workspace = workspace_manager

    def wait_for_human_review(self,
                              filename: str,
                              prompt_msg: Optional[str] = None) -> bool:
        """
        暂停执行，等待用户审查并编辑指定文件。

        Args:
            filename (str): 相对于工作区的文件名 (e.g. "tech_spec.md")。
            prompt_msg (str): 提示用户的自定义消息。

        Returns:
            bool: 如果用户选择继续，返回 True；如果用户选择退出，返回 False。
        """
        file_path = self.workspace.get_path(filename)

        if not file_path.exists():
            logger.warning(f'文件 {filename} 不存在，无法进行审查。')
            return True

        print('\n' + '=' * 60)
        print('🛑 [Human Review Required]')
        print(f'📄 File: {file_path}')
        if prompt_msg:
            print(f'💡 {prompt_msg}')
        else:
            print('💡 请打开上述文件进行检查。如果您修改了内容，保存文件即可。    ')

        print('-' * 60)
        print('选项 Options:')
        print('  [C]ontinue : 确认内容无误 (或已保存修改)，继续执行')
        print('  [R]eload   : 重新读取文件内容并打印预览 (检查修改是否生效)')
        print('  [E]xit     : 终止任务')
        print('=' * 60 + '\n')

        while True:
            choice = input('Your choice [C/R/E]: ').strip().upper()

            if choice == 'C':
                logger.info(f'User approved {filename}. Continuing...')
                return True
            elif choice == 'E':
                logger.info('User aborted the process.')
                return False
            elif choice == 'R':
                print(f'\n--- Preview of {filename} ---')
                print(file_path.read_text(encoding='utf-8'))
                print('-' * 30 + '\n')
            else:
                print('Invalid choice. Please enter C, R, or E.')
