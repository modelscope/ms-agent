# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional, Union

import json
import numpy as np
import pandas as pd
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.findata.akshare_source import AKShareDataSource
from ms_agent.tools.findata.baostock_source import BaoStockDataSource
from ms_agent.tools.findata.data_source_base import (DataSourceError,
                                                     FinancialDataSource,
                                                     NoDataFoundError)
from ms_agent.tools.findata.hybrid_source import HybridDataSource
from ms_agent.utils import get_logger
from ms_agent.utils.rate_limiter import AdaptiveRateLimiter, RateLimiter
from omegaconf import DictConfig

logger = get_logger()


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for handling date/datetime/numpy types"""

    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, pd.Period):
            return str(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):
            return None
        return super().default(obj)


class FinancialDataFetcher(ToolBase):
    """
    Financial Data Fetcher Tool

    Supported data sources:
    - baostock: A-share specific, high data quality
    - akshare: Multi-market support (A-shares, HK stocks, US stocks)
    - hybrid: Smart hybrid (recommended)
    """

    def __init__(self, config: Optional[DictConfig] = None):
        super().__init__(config)
        tools_cfg = getattr(config, 'tools',
                            None) if config is not None else None
        self.exclude_func(getattr(tools_cfg, 'financial_data_fetcher', None))
        self.save_dir = getattr(config, 'output_dir', './output')

        # Create financial_data directory
        self.financial_data_dir = Path(self.save_dir) / 'financial_data'
        self.financial_data_dir.mkdir(parents=True, exist_ok=True)

        # Configuration for sample data
        self.sample_rows = 10  # Number of sample rows to return

        self.data_source: Optional[FinancialDataSource] = None
        self.source_type = self._get_source_type(config)

        # Initialize rate limiter
        self.rate_limiter = self._create_rate_limiter(config)
        max_workers = self.rate_limiter.max_concurrent if self.rate_limiter else 1
        self.thread_pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='financial_data_fetcher_',
        )

        logger.info(
            f'Initializing FinancialDataFetcher with source: {self.source_type}'
        )
        logger.info(
            f'Financial data will be saved to: {self.financial_data_dir}')

    def _get_source_type(self, config: Optional[DictConfig]) -> str:
        """Get data source type from config"""
        if isinstance(config,
                      DictConfig) and hasattr(config, 'tools') and hasattr(
                          config.tools, 'financial_data_fetcher'):
            return getattr(config.tools.financial_data_fetcher, 'source_type',
                           'hybrid')

        return 'hybrid'

    def _create_rate_limiter(
        self, config: Optional[DictConfig]
    ) -> Optional[Union[RateLimiter, AdaptiveRateLimiter]]:
        """
        Create rate limiter from config.

        Config example in YAML:
        ```yaml
        tools:
          financial_data_fetcher:
            rate_limiter:
              enabled: true
              type: adaptive  # or 'basic'
              # Basic RateLimiter parameters
              max_requests_per_second: 2
              min_request_interval: 0.5
              max_concurrent: 3
              # AdaptiveRateLimiter additional parameters
              initial_requests_per_second: 2
              min_requests_per_second: 1
              max_requests_per_second: 5
              backoff_factor: 0.5
              recovery_factor: 1.2
              error_threshold: 3
              success_threshold: 10
        ```
        """
        # Check if rate limiter is configured
        if not (isinstance(config, DictConfig) and hasattr(config, 'tools')
                and hasattr(config.tools, 'financial_data_fetcher')):
            logger.info(
                'No rate limiter configured, running without rate limiting')
            return None

        fetcher_config = config.tools.financial_data_fetcher
        if not hasattr(fetcher_config, 'rate_limiter'):
            logger.info(
                'No rate limiter configured, running without rate limiting')
            return None

        rl_config = fetcher_config.rate_limiter

        # Check if rate limiter is enabled
        if not getattr(rl_config, 'enabled', False):
            logger.info('Rate limiter disabled in config')
            return None

        limiter_type = getattr(rl_config, 'type', 'basic').lower()

        if limiter_type == 'adaptive':
            # Create AdaptiveRateLimiter
            params = {
                'initial_requests_per_second':
                getattr(rl_config, 'initial_requests_per_second', 2),
                'min_requests_per_second':
                getattr(rl_config, 'min_requests_per_second', 1),
                'max_requests_per_second':
                getattr(rl_config, 'max_requests_per_second', 5),
                'min_request_interval':
                getattr(rl_config, 'min_request_interval', 0.5),
                'max_concurrent':
                getattr(rl_config, 'max_concurrent', 3),
                'backoff_factor':
                getattr(rl_config, 'backoff_factor', 0.5),
                'recovery_factor':
                getattr(rl_config, 'recovery_factor', 1.2),
                'error_threshold':
                getattr(rl_config, 'error_threshold', 3),
                'success_threshold':
                getattr(rl_config, 'success_threshold', 10),
            }
            logger.info(f'Creating AdaptiveRateLimiter with params: {params}')
            return AdaptiveRateLimiter(**params)

        elif limiter_type == 'basic':
            # Create basic RateLimiter
            params = {
                'max_requests_per_second':
                getattr(rl_config, 'max_requests_per_second', 2),
                'min_request_interval':
                getattr(rl_config, 'min_request_interval', 0.5),
                'max_concurrent':
                getattr(rl_config, 'max_concurrent', 3),
            }
            logger.info(f'Creating RateLimiter with params: {params}')
            return RateLimiter(**params)

        else:
            logger.warning(
                f'Unknown rate limiter type: {limiter_type}, running without rate limiting'
            )
            return None

    def _create_data_source(self) -> FinancialDataSource:
        """Create data source instance"""
        source_map = {
            'baostock': BaoStockDataSource,
            'akshare': AKShareDataSource,
            'hybrid': HybridDataSource,
        }

        source_class = source_map.get(self.source_type.lower())
        if not source_class:
            logger.warning(
                f'Unknown source type: {self.source_type}, using hybrid')
            source_class = HybridDataSource

        return source_class()

    async def connect(self) -> None:
        """Initialize data source connection"""
        if self.data_source is None:
            logger.info(f'Connecting to {self.source_type} data source')
            self.data_source = self._create_data_source()
            logger.info('Data source connected successfully')

    async def cleanup(self) -> None:
        """Clean up resources"""
        logger.info('Cleaning up FinancialDataFetcher resources')
        self.data_source = None

    async def _execute_with_rate_limit(self, func, *args, **kwargs):
        """
        Execute a function with rate limiting if configured.

        Args:
            func: The function to execute ( can be sync or async)
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
        """
        if self.rate_limiter is None:
            # No rate limiting, execute directly in thread pool
            return await asyncio.to_thread(func, *args, **kwargs)

        # Execute with rate limiting
        try:
            loop = asyncio.get_event_loop()
            func_with_args = partial(func, *args, **kwargs)

            async with self.rate_limiter:
                result = await loop.run_in_executor(self.thread_pool,
                                                    func_with_args)

            # Record success if using adaptive rate limiter
            if isinstance(self.rate_limiter, AdaptiveRateLimiter):
                self.rate_limiter.record_success()

            return result

        except Exception as e:
            if isinstance(self.rate_limiter, AdaptiveRateLimiter):
                error_msg = str(e).lower()
                is_rate_limit_error = any(keyword in error_msg for keyword in [
                    'rate limit', 'too many requests', 'quota exceeded', '429'
                ])
                self.rate_limiter.record_error(is_rate_limit_error)

            raise

    def _save_dataframe(self, df, filename: str) -> str:
        """
        Save DataFrame to file in financial_data directory.

        Args:
            df: DataFrame to save
            filename: Filename (without extension)

        Returns:
            Full path to saved file
        """
        try:
            filepath = self.financial_data_dir / f'{filename}.csv'
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            logger.info(f'Data saved to: {filepath}')
            return str(filepath)
        except Exception as e:
            logger.error(
                f'Failed to save data to {filename}: {e}', exc_info=True)
            return ''

    def _create_success_response(self,
                                 df,
                                 saved_path: str,
                                 metadata: Optional[Dict] = None) -> str:
        """
        Create success response with sample data.

        Args:
            df: Full DataFrame
            saved_path: Path where data was saved
            metadata: Additional metadata to include

        Returns:
            JSON string with sample data and metadata
        """
        response = {
            'success': True,
            'saved_to': saved_path,
            'total_rows': len(df),
            'columns': list(df.columns),
        }

        # Add sample data (first N rows)
        if len(df) > 0:
            sample_df = df.head(self.sample_rows)
            response['example_data'] = sample_df.to_dict(orient='records')
            if len(df) > self.sample_rows:
                response['note'] = (
                    f'Showing {self.sample_rows} sample rows out of {len(df)} '
                    f'total rows. Full data saved to file.')
        else:
            response['example_data'] = []
            response['note'] = 'No data returned'

        # Add any additional metadata
        if metadata:
            response.update(metadata)

        return json.dumps(
            response, ensure_ascii=False, indent=2, cls=DateTimeEncoder)

    def _create_error_response(self, error: Exception, operation: str,
                               params: Dict) -> str:
        """
        Create standardized error response.

        Args:
            error: The exception that occurred
            operation: Name of the operation that failed
            params: Parameters used in the operation

        Returns:
            JSON string with error details
        """
        error_type = type(error).__name__
        error_msg = str(error)

        response = {
            'success': False,
            'operation': operation,
            'error_type': error_type,
            'error': error_msg,
            'parameters': params
        }

        # Only log with traceback for unexpected errors
        # For known data source errors, just log the message
        if isinstance(error, (DataSourceError, NoDataFoundError)):
            logger.warning(f'{operation}: {error_msg}')
        else:
            logger.error(
                f"Operation '{operation}' failed: {error_type} - {error_msg}",
                exc_info=True)

        return json.dumps(
            response, ensure_ascii=False, indent=2, cls=DateTimeEncoder)

    async def _get_tools_inner(self) -> Dict[str, Any]:
        """Return tool definitions"""
        tools = {
            'financial_data_fetcher': [
                Tool(
                    tool_name='get_historical_k_data',
                    server_name='financial_data_fetcher',
                    description=
                    'Get historical K-line data (daily, weekly, monthly, etc.)',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Stock code, e.g. sh.600000 (Shanghai), sz.000001 (Shenzhen)'
                                 'hk.03690 (Hong Kong), us.AAPL (US)')
                            },
                            'start_date': {
                                'type': 'string',
                                'description': 'Start date, format: YYYY-MM-DD'
                            },
                            'end_date': {
                                'type': 'string',
                                'description': 'End date, format: YYYY-MM-DD'
                            },
                            'frequency': {
                                'type': 'string',
                                'description':
                                'Data frequency: d(daily), w(weekly), m(monthly), 5/15/30/60(minutes)',
                                'default': 'd'
                            },
                            'adjust_flag': {
                                'type':
                                'string',
                                'description':
                                ('Adjustment flag for historical data.'
                                 'Adjust type: 1(backward adjusted), 2(forward adjusted), 3(non-adjusted)'
                                 ),
                                'default':
                                '3'
                            }
                        },
                        'required':
                        ['code', 'start_date', 'end_date', 'frequency'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_stock_basic_info',
                    server_name='financial_data_fetcher',
                    description=
                    'Get stock basic information (name, industry, listing date, etc.)',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Stock code, e.g. sh.600000 (Shanghai), sz.000001 (Shenzhen)'
                                 'hk.03690 (Hong Kong), us.AAPL (US)')
                            }
                        },
                        'required': ['code'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_dividend_data',
                    server_name='financial_data_fetcher',
                    description='Fetches dividend information.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Stock code, e.g. sh.600000 (Shanghai), sz.000001 (Shenzhen)'
                                 'hk.03690 (Hong Kong), us.AAPL (US)')
                            },
                            'year': {
                                'type':
                                'string',
                                'description':
                                'Year, e.g. 2023. If not provided, the current year will be used'
                            },
                            'year_type': {
                                'type':
                                'string',
                                'description':
                                ('Year category, default is "report": Year of the preliminary '
                                 'announcement, optional "operate": Year of ex-dividend and ex-rights'
                                 ),
                                'default':
                                'report',
                                'enum': ['report', 'operate']
                            }
                        },
                        'required': ['code'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_adjust_factor_data',
                    server_name='financial_data_fetcher',
                    description='Get adjustment factor data',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type': 'string',
                                'description': 'Stock code',
                            },
                            'start_date': {
                                'type': 'string',
                                'description':
                                'Start date, format: YYYY-MM-DD.'
                            },
                            'end_date': {
                                'type': 'string',
                                'description': 'End date, format: YYYY-MM-DD.'
                            }
                        },
                        'required': ['code', 'start_date', 'end_date'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_financial_data',
                    server_name='financial_data_fetcher',
                    description=
                    ('Get quarterly financial data for a given stock.'
                     'Supported data types: profit, operation, growth, balance, cash_flow, dupont.'
                     'You can specify one or multiple data types to get the corresponding data.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Stock code, e.g. sh.600000 (Shanghai), sz.000001 (Shenzhen)'
                                 'hk.03690 (Hong Kong), us.AAPL (US)')
                            },
                            'year': {
                                'type': 'string',
                                'description': 'Year, e.g. 2023'
                            },
                            'quarter': {
                                'type':
                                'integer',
                                'description':
                                ('Quarter, 1-4, e.g. 1 for first quarter, 2 for second '
                                 'quarter, 3 for third quarter, 4 for fourth quarter'
                                 )
                            },
                            'data_types': {
                                'type': 'array',
                                'description': 'Data types to get.',
                                'items': {
                                    'type':
                                    'string',
                                    'enum': [
                                        'profit', 'operation', 'growth',
                                        'balance', 'cash_flow', 'dupont'
                                    ]
                                }
                            }
                        },
                        'required': ['code', 'year', 'quarter'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_report',
                    server_name='financial_data_fetcher',
                    description=
                    ('Get report data for a given stock. Support for performance express '
                     'reports and performance forecast reports'),
                    parameters={
                        'type':
                        'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Stock code, e.g. sh.600000 (Shanghai), sz.000001 (Shenzhen)'
                                 'hk.03690 (Hong Kong), us.AAPL (US)')
                            },
                            'start_date': {
                                'type': 'string',
                                'description': 'Start date, format: YYYY-MM-DD'
                            },
                            'end_date': {
                                'type': 'string',
                                'description': 'End date, format: YYYY-MM-DD'
                            },
                            'report_type': {
                                'type':
                                'string',
                                'description':
                                'Report type',
                                'default':
                                'performance_express',
                                'enum': [
                                    'performance_express',
                                    'performance_forecast'
                                ]
                            }
                        },
                        'required':
                        ['code', 'start_date', 'end_date', 'report_type'],
                        'additionalProperties':
                        False
                    }),
                Tool(
                    tool_name='get_stock_industry',
                    server_name='financial_data_fetcher',
                    description=
                    'Get industry classification for a given stock and date',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Stock code, e.g. sh.600000 (Shanghai), sz.000001 (Shenzhen)'
                                 'hk.03690 (Hong Kong), us.AAPL (US)')
                            },
                            'date': {
                                'type': 'string',
                                'description': 'Query date, format: YYYY-MM-DD'
                            }
                        },
                        'required': ['code', 'date'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_stock_list',
                    server_name='financial_data_fetcher',
                    description=
                    ('Get stock list for a given date, support for SSE 50 index constituents (sse50), '
                     'CSI 300 index constituents (hs300), CSI 500 index constituents (zz500) '
                     'and all a-share stocks (all_a_share)'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'date': {
                                'type': 'string',
                                'description': 'Query date, format: YYYY-MM-DD'
                            },
                            'data_type': {
                                'type': 'string',
                                'description':
                                'Data type to get. Default is "all_a_share"',
                                'enum':
                                ['sse50', 'hs300', 'zz500', 'all_a_share']
                            }
                        },
                        'required': ['date'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_trade_dates',
                    server_name='financial_data_fetcher',
                    description='Get trading dates information within a range',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'start_date': {
                                'type': 'string',
                                'description': 'Start date, format: YYYY-MM-DD'
                            },
                            'end_date': {
                                'type': 'string',
                                'description': 'End date, format: YYYY-MM-DD'
                            }
                        },
                        'required': [],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_macro_data',
                    server_name='financial_data_fetcher',
                    description=
                    ('Get macro data for a given range of dates'
                     'Supported data types: deposit_rate, loan_rate, required_reserve_ratio, money_supply_month, '
                     'money_supply_year'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'start_date': {
                                'type': 'string',
                                'description': 'Start date, format: YYYY-MM-DD'
                            },
                            'end_date': {
                                'type': 'string',
                                'description': 'End date, format: YYYY-MM-DD'
                            },
                            'data_types': {
                                'type': 'array',
                                'description':
                                'Data types to get. Default is all data types',
                                'items': {
                                    'type':
                                    'string',
                                    'enum': [
                                        'deposit_rate', 'loan_rate',
                                        'required_reserve_ratio',
                                        'money_supply_month',
                                        'money_supply_year'
                                    ]
                                },
                            },
                            'extra_kwargs': {
                                'type': 'object',
                                'description':
                                'Extra keyword arguments for the macro data',
                                'properties': {
                                    'yearType': {
                                        'type':
                                        'string',
                                        'description':
                                        ('Year Type, default value 0 means "announcement date," '
                                         'and 1 means "effective date".'),
                                        'default':
                                        '0'
                                    }
                                },
                                'required': [],  # yearType is optional
                                'additionalProperties': False
                            }
                        },
                        'required': ['start_date', 'end_date', 'data_types'],
                        'additionalProperties': False
                    },
                )
            ]
        }

        # Update tools by source type
        if self.data_source is not None and hasattr(self.data_source,
                                                    'get_extra_tools'):
            tools.update(self.data_source.get_extra_tools())
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        """Call tool method"""
        if self.data_source is None:
            await self.connect()

        return await getattr(self, tool_name)(**tool_args)

    async def get_historical_k_data(self,
                                    code: str,
                                    start_date: str,
                                    end_date: str,
                                    frequency: str = 'd',
                                    adjust_flag: str = '3') -> str:
        """Get historical K-line data"""
        params = {
            'code': code,
            'start_date': start_date,
            'end_date': end_date,
            'frequency': frequency,
            'adjust_flag': adjust_flag
        }

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_historical_k_data,
                code=code,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjust_flag=adjust_flag)

            # Generate filename with key parameters
            clean_code = code.replace('.', '_')
            filename = f'k_data_{clean_code}_{start_date}_{end_date}_freq{frequency}_adj{adjust_flag}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {
                'code': code,
                'date_range': f'{start_date} to {end_date}',
                'frequency': frequency,
                'adjust_flag': adjust_flag
            }
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_historical_k_data',
                                               params)

    async def get_stock_basic_info(self, code: str) -> str:
        """Get stock basic information"""
        params = {'code': code}

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_stock_basic_info, code=code)

            # Generate filename
            clean_code = code.replace('.', '_')
            filename = f'basic_info_{clean_code}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {'code': code}
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_stock_basic_info',
                                               params)

    async def get_dividend_data(self,
                                code: str,
                                year: Optional[str] = None,
                                year_type: str = 'report') -> str:
        """Get dividend information (BaoStock)."""
        params = {'code': code, 'year': year, 'year_type': year_type}

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_dividend_data,
                code=code,
                year=year,
                year_type=year_type)

            # Generate filename
            clean_code = code.replace('.', '_')
            year_str = year if year else 'all'
            filename = f'dividend_{clean_code}_{year_str}_{year_type}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {'code': code, 'year': year, 'year_type': year_type}
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_dividend_data', params)

    async def get_adjust_factor_data(self, code: str, start_date: str,
                                     end_date: str) -> str:
        """Get adjustment factor data (BaoStock)."""
        params = {'code': code, 'start_date': start_date, 'end_date': end_date}

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_adjust_factor_data,
                code=code,
                start_date=start_date,
                end_date=end_date)

            # Generate filename
            clean_code = code.replace('.', '_')
            filename = f'adjust_factor_{clean_code}_{start_date}_{end_date}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {
                'code': code,
                'date_range': f'{start_date} to {end_date}'
            }
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_adjust_factor_data',
                                               params)

    async def get_financial_data(self,
                                 code: str,
                                 year: str,
                                 quarter: int,
                                 data_types: Optional[list] = None) -> str:
        """Get multiple categories of financial data in one call."""
        data_types = data_types or [
            'profit', 'operation', 'growth', 'balance', 'cash_flow', 'dupont'
        ]
        params = {
            'code': code,
            'year': year,
            'quarter': quarter,
            'data_types': data_types
        }

        try:
            result = await self._execute_with_rate_limit(
                self.data_source.get_financial_data,
                code=code,
                year=year,
                quarter=quarter,
                data_types=data_types)

            # Save each data type and prepare response
            clean_code = code.replace('.', '_')
            saved_files = {}
            example_data = {}

            for key, value in result.items():
                if hasattr(value, 'to_dict'):
                    # Save each type of financial data
                    filename = f'financial_{key}_{clean_code}_{year}_Q{quarter}'
                    saved_path = self._save_dataframe(value, filename)
                    saved_files[key] = saved_path

                    # Create sample data for each type
                    sample_df = value.head(self.sample_rows)
                    example_data[key] = sample_df.to_dict(orient='records')
                else:
                    example_data[key] = value

            response = {
                'success':
                True,
                'code':
                code,
                'year':
                year,
                'quarter':
                quarter,
                'data_types':
                list(result.keys()),
                'saved_files':
                saved_files,
                'example_data':
                example_data,
                'note':
                'Financial data saved to separate files. Showing sample rows for each data type.'
            }

            return json.dumps(
                response, ensure_ascii=False, indent=2, cls=DateTimeEncoder)

        except Exception as e:
            return self._create_error_response(e, 'get_financial_data', params)

    async def get_report(self,
                         code: str,
                         start_date: str,
                         end_date: str,
                         report_type: str = 'performance_express') -> str:
        """Get performance express/forecast reports (BaoStock)."""
        params = {
            'code': code,
            'start_date': start_date,
            'end_date': end_date,
            'report_type': report_type
        }

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_report,
                code=code,
                start_date=start_date,
                end_date=end_date,
                report_type=report_type)

            # Generate filename
            clean_code = code.replace('.', '_')
            filename = f'report_{report_type}_{clean_code}_{start_date}_{end_date}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {
                'code': code,
                'date_range': f'{start_date} to {end_date}',
                'report_type': report_type
            }
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_report', params)

    async def get_trade_dates(self, start_date: str, end_date: str) -> str:
        """Get trading calendar"""
        params = {'start_date': start_date, 'end_date': end_date}

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_trade_dates,
                start_date=start_date,
                end_date=end_date)

            # Generate filename
            filename = f'trade_dates_{start_date}_{end_date}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {'date_range': f'{start_date} to {end_date}'}
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_trade_dates', params)

    async def get_stock_industry(self, code: str, date: str) -> str:
        """Get industry classification (BaoStock)."""
        params = {'code': code, 'date': date}

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_stock_industry, code=code, date=date)

            # Generate filename
            clean_code = code.replace('.', '_')
            filename = f'industry_{clean_code}_{date}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {'code': code, 'date': date}
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_stock_industry', params)

    async def get_stock_list(self,
                             date: str,
                             data_type: str = 'all_a_share') -> str:
        """Get index constituents or all stocks."""
        params = {'date': date, 'data_type': data_type}

        try:
            df = await self._execute_with_rate_limit(
                self.data_source.get_stock_list,
                date=date,
                data_type=data_type)

            # Generate filename
            filename = f'stock_list_{data_type}_{date}'

            # Save data
            saved_path = self._save_dataframe(df, filename)

            # Return response with sample data
            metadata = {
                'date': date,
                'data_type': data_type,
                'total_stocks': len(df)
            }
            return self._create_success_response(df, saved_path, metadata)

        except Exception as e:
            return self._create_error_response(e, 'get_stock_list', params)

    async def get_macro_data(self,
                             start_date: str,
                             end_date: str,
                             data_types: Optional[list] = None,
                             extra_kwargs: Optional[dict] = None) -> str:
        """Get macroeconomic data (BaoStock)."""
        data_types = data_types or [
            'deposit_rate', 'loan_rate', 'required_reserve_ratio',
            'money_supply_month', 'money_supply_year'
        ]
        params = {
            'start_date': start_date,
            'end_date': end_date,
            'data_types': data_types,
            'extra_kwargs': extra_kwargs
        }

        try:
            result = await self._execute_with_rate_limit(
                self.data_source.get_macro_data,
                start_date=start_date,
                end_date=end_date,
                data_types=data_types,
                extra_kwargs=extra_kwargs)

            # Save each data type and prepare response
            saved_files = {}
            example_data = {}

            for key, value in result.items():
                if hasattr(value, 'to_dict'):
                    # Save each type of macro data
                    filename = f'macro_{key}_{start_date}_{end_date}'
                    saved_path = self._save_dataframe(value, filename)
                    saved_files[key] = saved_path

                    # Create sample data for each type
                    sample_df = value.head(self.sample_rows)
                    example_data[key] = sample_df.to_dict(orient='records')
                else:
                    example_data[key] = value

            response = {
                'success':
                True,
                'date_range':
                f'{start_date} to {end_date}',
                'data_types':
                list(result.keys()),
                'saved_files':
                saved_files,
                'example_data':
                example_data,
                'note':
                'Macro data saved to separate files. Showing sample rows for each data type.'
            }

            return json.dumps(
                response, ensure_ascii=False, indent=2, cls=DateTimeEncoder)

        except Exception as e:
            return self._create_error_response(e, 'get_macro_data', params)
