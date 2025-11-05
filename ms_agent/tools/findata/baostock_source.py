# Copyright (c) Alibaba, Inc. and its affiliates.
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Dict, List, Optional

import baostock as bs
import pandas as pd
from ms_agent.tools.findata.data_source_base import (DataSourceError,
                                                     FinancialDataSource,
                                                     NoDataFoundError)
from ms_agent.utils import get_logger

logger = get_logger()


class BaoStockSessionManager:
    """Thread-safe BaoStock session manager with connection reuse"""
    _instance = None
    _lock = threading.Lock()
    _session_lock = threading.Lock()
    _login_count = 0
    _is_logged_in = False
    _idle_timeout = 300  # 5 minutes
    _timer: Optional[threading.Timer] = None

    def _schedule_logout(self):
        if self._timer:
            return
        self._timer = threading.Timer(self._idle_timeout, self._force_logout)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_logout(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _force_logout(self):
        with self._session_lock:
            if self._login_count == 0 and self._is_logged_in:
                bs.logout()
                self._is_logged_in = False
                logger.debug('BaoStock session closed by idle-timeout')
            self._timer = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def ensure_login(self):
        """Ensure BaoStock is logged in (thread-safe)"""
        with self._session_lock:
            if not self._is_logged_in:
                lg = bs.login()
                if lg.error_code != '0':
                    raise DataSourceError(
                        f'BaoStock login failed: {lg.error_msg}')
                self._is_logged_in = True
                self._login_count = 1
                logger.debug('BaoStock session established')
            else:
                self._login_count += 1
                # Someone reused the session within idle timeout; cancel scheduled logout
                self._cancel_logout()
                logger.debug(
                    f'BaoStock session reused (count: {self._login_count})')

    def release(self):
        """Release session (logout only when no active users)"""
        with self._session_lock:
            self._login_count -= 1
            if self._login_count <= 0:
                self._login_count = 0
                self._schedule_logout()


@contextmanager
def baostock_session():
    """BaoStock session context manager with connection reuse"""
    manager = BaoStockSessionManager()
    manager.ensure_login()
    try:
        yield
    finally:
        manager.release()


class BaoStockDataSource(FinancialDataSource):
    """
    BaoStock Data Source Implementation

    Provides A-share market data:
    - Historical K-line data
    - Stock basic information
    - Financial indicator data
    - Macroeconomic data
    """

    DEFAULT_K_FIELDS = [
        'date', 'code', 'open', 'high', 'low', 'close', 'preclose', 'volume',
        'amount', 'adjustflag', 'turn', 'tradestatus', 'pctChg', 'peTTM',
        'pbMRQ', 'psTTM', 'pcfNcfTTM', 'isST'
    ]

    def __init__(self):
        logger.info('Initializing BaoStock data source')
        # Test connection
        with baostock_session():
            logger.info('BaoStock connection successful')

    def _query_to_dataframe(self, rs, data_type: str = 'data') -> pd.DataFrame:
        """Convert BaoStock query result to DataFrame"""
        if rs.error_code != '0':
            if 'no record found' in rs.error_msg.lower(
            ) or rs.error_code == '10002':
                raise NoDataFoundError(f'No {data_type} found: {rs.error_msg}')
            raise DataSourceError(
                f'BaoStock API error: {rs.error_msg} (code: {rs.error_code})')

        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            raise NoDataFoundError(f'No {data_type} found (empty result)')

        return pd.DataFrame(data_list, columns=rs.fields)

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
        fields_str = ','.join(fields or self.DEFAULT_K_FIELDS)

        logger.info(f'Fetching K-data for {code} ({start_date} to {end_date})')

        with baostock_session():
            rs = bs.query_history_k_data_plus(
                code=code,
                fields=fields_str,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjust_flag)
            return self._query_to_dataframe(rs, f'K-data for {code}')

    def get_stock_basic_info(self, code: str) -> pd.DataFrame:
        """Get stock basic information"""
        logger.info(f'Fetching basic info for {code}')

        with baostock_session():
            rs = bs.query_stock_basic(code=code)
            return self._query_to_dataframe(rs, f'basic info for {code}')

    def get_dividend_data(self,
                          code: str,
                          year: Optional[str] = None,
                          year_type: str = 'report') -> pd.DataFrame:
        """Get dividend data"""
        logger.info(f'Fetching dividend data for {code} ({year} {year_type})')

        with baostock_session():
            rs = bs.query_dividend_data(
                code=code, year=year, yearType=year_type)
            return self._query_to_dataframe(
                rs, f'dividend data for {code} ({year} {year_type})')

    def get_adjust_factor_data(self, code: str, start_date: str,
                               end_date: str) -> pd.DataFrame:
        """Get adjustment factor data"""
        logger.info(
            f'Fetching adjustment factor data for {code} ({start_date} to {end_date})'
        )

        with baostock_session():
            rs = bs.query_adjust_factor(
                code=code, start_date=start_date, end_date=end_date)
            return self._query_to_dataframe(
                rs,
                f'adjustment factor data for {code} ({start_date} to {end_date})'
            )

    def get_financial_data(self, code: str, year: str, quarter: int,
                           data_types: List[str]) -> Dict[str, pd.DataFrame]:
        """Get financial data"""
        logger.info(
            f'Fetching financial data for {code} ({year}Q{quarter}) {data_types}'
        )

        if not data_types:
            raise ValueError('data_types cannot be empty')

        result = {}
        with baostock_session():
            for data_type in data_types:
                if data_type == 'profit':
                    query_func = bs.query_profit_data
                elif data_type == 'operation':
                    query_func = bs.query_operation_data
                elif data_type == 'growth':
                    query_func = bs.query_growth_data
                elif data_type == 'balance':
                    query_func = bs.query_balance_data
                elif data_type == 'cash_flow':
                    query_func = bs.query_cash_flow_data
                elif data_type == 'dupont':
                    query_func = bs.query_dupont_data
                else:
                    raise ValueError(f'Invalid data type: {data_type}')

                df = self._query_financial_data(query_func, data_type, code,
                                                year, quarter)
                result[data_type] = df

        if not result:
            raise NoDataFoundError(
                f'No financial data found for {code} ({year}Q{quarter})')

        return result

    def _query_financial_data(self, query_func, data_type: str, code: str,
                              year: str, quarter: int) -> pd.DataFrame:
        """Query financial data using provided function (assumes session is already active)"""
        logger.info(f'Fetching {data_type} for {code} ({year}Q{quarter})')

        rs = query_func(code=code, year=year, quarter=quarter)
        return self._query_to_dataframe(rs, f'{data_type} for {code}')

    def get_report(self,
                   code: str,
                   start_date: str,
                   end_date: str,
                   report_type: str = '') -> pd.DataFrame:
        """Get report data"""
        logger.info(
            f'Fetching report data for {code} ({start_date} to {end_date}) {report_type}'
        )

        if not report_type:
            raise ValueError('report_type cannot be empty')

        with baostock_session():
            if report_type == 'performance_express':
                rs = bs.query_performance_express_report(
                    code=code, start_date=start_date, end_date=end_date)
            elif report_type == 'performance_forecast':
                rs = bs.query_forecast_report(
                    code=code, start_date=start_date, end_date=end_date)
            else:
                raise ValueError(f'Invalid report type: {report_type}')

            return self._query_to_dataframe(
                rs,
                f'report data for {code} ({start_date} to {end_date}) {report_type}'
            )

    def get_stock_industry(self,
                           code: Optional[str] = None,
                           date: Optional[str] = None) -> pd.DataFrame:
        """Get stock industry"""
        logger.info(
            f"Fetching stock industry for code={code or 'all'}, date={date or 'latest'}"
        )

        with baostock_session():
            rs = bs.query_stock_industry(code=code, date=date)
            return self._query_to_dataframe(
                rs, f'stock industry for {code or "all"} ({date or "latest"})')

    def get_stock_list(self,
                       date: str,
                       data_type: str = 'all_a_share') -> pd.DataFrame:
        """Get stock list or index constituents"""
        logger.info(
            f'Fetching stock list for {date} {data_type}, only support a_share'
        )

        with baostock_session():
            if data_type == 'sz50':
                rs = bs.query_sz50_stocks(date=date)
            elif data_type == 'hs300':
                rs = bs.query_hs300_stocks(date=date)
            elif data_type == 'zz500':
                rs = bs.query_zz500_stocks(date=date)
            elif data_type == 'all_a_share':
                rs = bs.query_all_stock(day=date)
            else:
                raise ValueError(f'Invalid data type: {data_type}')

            df = self._query_to_dataframe(
                rs, f'stock list for {date} {data_type}')
            logger.info(f'Stock list for {date} {data_type}: {df.head()}')

            return df

    def get_trade_dates(self,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> pd.DataFrame:
        """Get trading calendar"""
        logger.info(
            f"Fetching trade dates ({start_date or 'default'} to {end_date or 'default'})"
        )

        with baostock_session():
            rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)
            return self._query_to_dataframe(rs, 'trade dates')

    def get_macro_data(
        self,
        start_date: str,
        end_date: str,
        data_types: Optional[List[str]] = None,
        extra_kwargs: Optional[Dict[str,
                                    Any]] = None) -> Dict[str, pd.DataFrame]:
        """Fetch macroeconomic data"""
        if data_types is None:
            data_types = []
        if extra_kwargs is None:
            extra_kwargs = {}

        logger.info(
            f'Fetching macro data ({start_date} to {end_date}) {data_types}')

        result = {}
        with baostock_session():
            for data_type in data_types:
                parsed_extra_kwargs = {}
                parsed_start_date = start_date
                parsed_end_date = end_date

                if data_type == 'deposit_rate':
                    query_func = bs.query_deposit_rate_data

                elif data_type == 'loan_rate':
                    query_func = bs.query_loan_rate_data

                elif data_type == 'required_reserve_ratio':
                    query_func = bs.query_required_reserve_ratio_data
                    if extra_kwargs:
                        parsed_extra_kwargs.update(extra_kwargs)
                    if 'yearType' not in parsed_extra_kwargs:
                        parsed_extra_kwargs['yearType'] = '0'

                elif data_type == 'money_supply_month':
                    query_func = bs.query_money_supply_data_month
                    parsed_start_date = pd.to_datetime(start_date).strftime(
                        '%Y-%m')
                    parsed_end_date = pd.to_datetime(end_date).strftime(
                        '%Y-%m')

                elif data_type == 'money_supply_year':
                    query_func = bs.query_money_supply_data_year
                    parsed_start_date = pd.to_datetime(start_date).strftime(
                        '%Y')
                    parsed_end_date = pd.to_datetime(end_date).strftime('%Y')

                else:
                    raise ValueError(f'Invalid data type: {data_type}')

                df = self._query_macro_data(query_func, data_type,
                                            parsed_start_date, parsed_end_date,
                                            **parsed_extra_kwargs)
                result[data_type] = df

        if not result:
            raise NoDataFoundError(
                'No macro data found for the specified criteria')
        return result

    def _query_macro_data(self, query_func, data_type: str, start_date: str,
                          end_date: str, **kwargs) -> pd.DataFrame:
        """Query macro data using provided function (assumes session is already active)"""
        logger.info(f'Fetching {data_type} for {start_date} to {end_date}')

        try:
            rs = query_func(start_date=start_date, end_date=end_date, **kwargs)
            return self._query_to_dataframe(
                rs, f'{data_type} for {start_date} to {end_date}')

        except Exception as e:
            logger.warning(f'Failed to fetch {data_type} data: {e}')
            return pd.DataFrame()
