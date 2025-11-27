import argparse
import sys
from pathlib import Path

from orchestrator.adapters.code_adapter import CodeAdapter
from orchestrator.adapters.deep_research_adapter import DeepResearchAdapter
# Adapters
from orchestrator.adapters.doc_research_adapter import DocResearchAdapter
from orchestrator.adapters.spec_adapter import SpecAdapter
from orchestrator.adapters.test_gen_adapter import TestGenAdapter
from orchestrator.core.config import OrchestratorConfig
from orchestrator.core.flow import FlowController
from orchestrator.core.workspace import WorkspaceManager
from orchestrator.utils.logger import setup_logger
from orchestrator.utils.verifier import run_pytest

# 确保能够导入 orchestrator 模块
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.append(str(project_root))


def main():
    """
    Orchestrator CLI 入口点。
    """
    parser = argparse.ArgumentParser(description='AI Agent Orchestrator CLI')

    parser.add_argument('query', type=str, help='用户的自然语言需求或问题')
    parser.add_argument('--files', nargs='*', help='附加的本地文件路径列表')
    parser.add_argument('--urls', nargs='*', help='附加的 URL 列表')
    parser.add_argument('--config', type=str, help='指定配置文件路径 (YAML)')
    parser.add_argument(
        '--mode',
        choices=['research_only', 'full'],
        default='full',
        help='运行模式')

    args = parser.parse_args()

    # 1. 初始化配置
    try:
        config = OrchestratorConfig.load()
        config.validate()
    except Exception as e:
        print(f'配置加载失败: {e}')
        sys.exit(1)

    # 2. 初始化工作区
    workspace = WorkspaceManager(root_path=config.workspace_root)

    # 3. 初始化组件
    logger = setup_logger(workspace.work_dir)
    flow = FlowController(workspace)

    logger.info('=== Orchestrator Started ===')
    logger.info(f'工作区: {workspace.work_dir}')

    # ==========================================
    # Phase 1: Research
    # ==========================================
    logger.info('\n--- Phase 1: Research ---')
    report_path = None

    try:
        if args.files or args.urls:
            logger.info('启动 DocResearchAdapter...')
            adapter = DocResearchAdapter(config, workspace)
            abs_files = [str(Path(f).resolve()) for f in (args.files or [])]
            res = adapter.run(
                query=args.query, files=abs_files, urls=args.urls or [])
        else:
            logger.info('启动 DeepResearchAdapter...')
            adapter = DeepResearchAdapter(config, workspace)
            res = adapter.run(query=args.query)

        report_path = res['report_path']
        logger.info(f'Research 完成! Report: {report_path}')

    except Exception as e:
        logger.error(f'Research 阶段失败: {e}', exc_info=True)
        sys.exit(1)

    if args.mode == 'research_only':
        return

    # ==========================================
    # Phase 2: Spec Generation
    # ==========================================
    logger.info('\n--- Phase 2: Spec Generation ---')
    spec_path = None
    try:
        adapter = SpecAdapter(config, workspace)
        res = adapter.run(report_path)
        spec_path = res['spec_path']
        logger.info(f'Spec 生成完成! Spec: {spec_path}')

        # HITL: 等待人工审查
        if not flow.wait_for_human_review('tech_spec.md',
                                          '请检查生成的技术规格书，确保API定义正确。'):
            sys.exit(0)

    except Exception as e:
        logger.error(f'Spec 阶段失败: {e}', exc_info=True)
        sys.exit(1)

    # ==========================================
    # Phase 3: Test Generation
    # ==========================================
    logger.info('\n--- Phase 3: Test Generation ---')
    tests_dir = None
    try:
        adapter = TestGenAdapter(config, workspace)
        res = adapter.run(spec_path)
        tests_dir = res['tests_dir']
        logger.info(f'Tests 生成完成! Dir: {tests_dir}')

    except Exception as e:
        logger.error(f'TestGen 阶段失败: {e}', exc_info=True)
        sys.exit(1)

    # ==========================================
    # Phase 4: Coding & Verify (Outer Loop)
    # ==========================================
    logger.info('\n--- Phase 4: Coding & Outer Loop ---')

    code_adapter = CodeAdapter(config, workspace)
    error_log = ''
    max_retries = config.max_retries
    retry_count = 0
    success = False

    while retry_count <= max_retries:
        logger.info(f'Attempt {retry_count + 1}/{max_retries + 1}')

        try:
            # 1. Generate Code
            res = code_adapter.run(
                query=args.query,
                spec_path=spec_path,
                tests_dir=tests_dir,
                error_log=error_log)
            src_dir = res['src_dir']
            logger.info(f'Coding 完成! Src: {src_dir}')

            # 2. Verify (Run Tests)
            logger.info('Running tests...')
            exit_code, stdout, stderr = run_pytest(tests_dir,
                                                   workspace.work_dir)

            if exit_code == 0:
                logger.info('✅ Tests Passed!')
                success = True
                break
            else:
                logger.warning(f'❌ Tests Failed (Exit Code: {exit_code})')
                logger.debug(f'Stdout: {stdout}')
                logger.debug(f'Stderr: {stderr}')

                # Prepare error log for next iteration
                error_log = f'Test Failure Output:\n{stdout}\n{stderr}'
                retry_count += 1

        except Exception as e:
            logger.error(f'Coding iteration failed: {e}', exc_info=True)
            retry_count += 1
            error_log = str(e)

    if success:
        logger.info('\n=== Orchestrator 流程成功结束 ===')
        logger.info(f'最终交付物: {workspace.work_dir}')
    else:
        logger.error('\n=== Orchestrator 流程失败: 达到最大重试次数 ===')
        sys.exit(1)


if __name__ == '__main__':
    main()
