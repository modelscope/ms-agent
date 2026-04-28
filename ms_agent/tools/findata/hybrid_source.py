# Copyright (c) ModelScope Contributors. All rights reserved.
import re
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from ms_agent.tools.findata.akshare_source import AKShareDataSource
from ms_agent.tools.findata.baostock_source import BaoStockDataSource
from ms_agent.tools.findata.data_source_base import (DataSourceError,
                                                     FinancialDataSource)
from ms_agent.utils import get_logger

logger = get_logger()


class HybridDataSource(FinancialDataSource):
    """
    Hybrid Data Source

    Automatic routing strategy:
    - A-share codes (sh.*, sz.*) -> BaoStock
    - HK stock codes (00700, 09988) -> AKShare
    - US stock codes (AAPL, TSLA) -> AKShare
    - Macroeconomic data -> BaoStock
    """

    def __init__(self):
        logger.info('Initializing Hybrid data source')
        self.baostock = BaoStockDataSource()
        self.akshare = AKShareDataSource()
        logger.info(
            'Hybrid data source initialized (A-shares: BaoStock, Others: AKShare)'
        )

    def _detect_market(self, code: str) -> str:
        """
        Detect market type, return 'a_share' for A-shares, 'hk_stock' for HK stocks,
        'us_stock' for US stocks, 'unknown' for unknown codes.
        """
        if not code:
            return 'unknown'

        code = code.upper().strip()

        # A-shares: sh.600000, sz.000001
        if (re.match(r'^(SH|SZ|BJ)\.\d{6}$', code)) or code.startswith(('SH.', 'SZ.', 'BJ.')):  # yapf: disable
            return 'a_share'

        # HK stocks: 00700, 09988 (4-5 digits)
        if re.match(r'^\d{4,5}$', code) or code.startswith('HK.'):
            return 'hk_stock'

        # US stocks: AAPL, TSLA (letters only)
        if re.match(r'^[A-Z]{1,5}$', code) or code.startswith('US.'):
            return 'us_stock'

        logger.warning(f'Unknown market type for code: {code}')
        return 'unknown'

    def _get_source(self,
                    code: str,
                    market: str = None) -> List[FinancialDataSource]:
        """Select data source based on stock code"""
        market = market if market else self._detect_market(code)

        if market == 'a_share':
            logger.debug(f'Using BaoStock for A-share: {code}')
            return [self.baostock, self.akshare]
        else:
            logger.debug(f'Using AKShare for {market}: {code}')
            return [self.akshare]

    def _call_sources(self, sources: List[FinancialDataSource],
                      query_func: Callable) -> pd.DataFrame:
        """Call query function for multiple data sources"""
        for source in sources:
            try:
                result = query_func(source)
                if isinstance(result, pd.DataFrame) and not result.empty:
                    return result
                if isinstance(result, dict) and result:
                    return result
            except Exception as e:
                logger.warning(
                    f'Data source {source.__class__.__name__} failed, continue to next source: {e}'
                )
                continue

        source_names = [s.__class__.__name__ for s in sources]
        raise DataSourceError(f'All data sources failed: {source_names}')

    def get_historical_k_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        frequency: str = 'd',
        adjust_flag: str = '3',
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Get historical K-line data"""
        sources = self._get_source(code)
        return self._call_sources(
            sources, lambda s: s.get_historical_k_data(
                code, start_date, end_date, frequency, adjust_flag, fields))

    def get_stock_basic_info(self, code: str) -> pd.DataFrame:
        """Get stock basic information"""
        sources = self._get_source(code)
        return self._call_sources(sources,
                                  lambda s: s.get_stock_basic_info(code))

    def get_dividend_data(self,
                          code: str,
                          year: Optional[str] = None,
                          year_type: str = 'report') -> pd.DataFrame:
        """Get dividend data (BaoStock only)"""
        sources = self._get_source(code)
        return self._call_sources(
            sources, lambda s: s.get_dividend_data(code, year, year_type))

    def get_adjust_factor_data(self, code: str, start_date: str,
                               end_date: str) -> pd.DataFrame:
        """Get adjustment factor data (BaoStock only)"""
        sources = self._get_source(code)
        return self._call_sources(
            sources,
            lambda s: s.get_adjust_factor_data(code, start_date, end_date))

    def get_financial_data(self, code: str, year: str, quarter: int,
                           data_types: List[str]) -> Dict[str, pd.DataFrame]:
        """Get financial data for multiple categories in one call"""
        sources = self._get_source(code)
        return self._call_sources(
            sources,
            lambda s: s.get_financial_data(code, year, quarter, data_types))

    def get_report(self,
                   code: str,
                   start_date: str,
                   end_date: str,
                   report_type: str = 'performance_express') -> pd.DataFrame:
        """Get report data (BaoStock only)"""
        sources = self._get_source(code)
        return self._call_sources(
            sources,
            lambda s: s.get_report(code, start_date, end_date, report_type))

    def get_stock_industry(self, code: str, date: str) -> pd.DataFrame:
        """Get industry classification (BaoStock only)"""
        sources = self._get_source(code)
        return self._call_sources(sources,
                                  lambda s: s.get_stock_industry(code, date))

    def get_stock_list(self,
                       date: str,
                       data_type: str = 'all_a_share') -> pd.DataFrame:
        """Get stock list or index constituents (BaoStock only)"""
        sources = self._get_source('', market='a_share')
        return self._call_sources(sources,
                                  lambda s: s.get_stock_list(date, data_type))

    def get_trade_dates(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Get trading calendar (BaoStock only)"""
        sources = self._get_source('', market='a_share')
        return self._call_sources(
            sources, lambda s: s.get_trade_dates(start_date, end_date))

    def get_macro_data(
        self,
        start_date: str,
        end_date: str,
        data_types: Optional[List[str]] = None,
        extra_kwargs: Optional[Dict[str,
                                    Any]] = None) -> Dict[str, pd.DataFrame]:
        """Get macroeconomic data for multiple categories in one call (BaoStock only)"""
        if data_types is None:
            data_types = []
        if extra_kwargs is None:
            extra_kwargs = {}

        sources = self._get_source('', market='a_share')
        return self._call_sources(
            sources, lambda s: s.get_macro_data(start_date, end_date,
                                                data_types, extra_kwargs))
