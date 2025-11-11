# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import Dict, Optional

from ms_agent.config.config import Config
from omegaconf import DictConfig, OmegaConf


class WorkflowLoader:

    @classmethod
    def build(cls,
              config_dir_or_id: Optional[str] = None,
              config: Optional[DictConfig] = None,
              env: Optional[Dict[str, str]] = None,
              trust_remote_code: bool = False,
              **kwargs):
        wf_config: Optional[DictConfig] = None
        if config_dir_or_id is not None:
            wf_config: DictConfig = Config.from_task(config_dir_or_id, env)
        if config is not None:
            if wf_config is not None:
                wf_config = OmegaConf.merge(wf_config, config)
            else:
                wf_config = config

        from ms_agent.workflow.chain_workflow import ChainWorkflow
        wf_type = ChainWorkflow.WORKFLOW_NAME.lower()
        wf_type = getattr(wf_config, 'type', '').lower() or wf_type

        if wf_type == ChainWorkflow.WORKFLOW_NAME.lower():
            wf_instance = ChainWorkflow(
                config_dir_or_id=config_dir_or_id,
                config=wf_config,
                env=env,
                mcp_server_file=kwargs.get('mcp_server_file'),
                load_cache=kwargs.get('load_cache', False),
                trust_remote_code=trust_remote_code)
        elif wf_type == 'ResearchWorkflow'.lower():
            # TODO
            raise NotImplementedError()
        else:
            raise ValueError(f'Unknown agent type: {wf_type}')

        return wf_instance
