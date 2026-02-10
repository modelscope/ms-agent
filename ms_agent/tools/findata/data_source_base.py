# Copyright (c) ModelScope Contributors. All rights reserved.
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd


class DataSourceError(Exception):
    """Base data source error class"""
    pass


class NoDataFoundError(DataSourceError):
    """Data not found exception"""
    pass


class FinancialDataSource(ABC):
    """
    Financial Data Source Abstract Base Class

    Defines core methods that all financial data sources must implement.
    Subclasses need to implement these methods to provide specific data fetching capabilities.
    """

    @abstractmethod
    def get_historical_k_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        frequency: str,
        adjust_flag: str,
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Get historical K-line data

        Args:
            code: Stock code (e.g. 'sh.600000', 'sz.000001')
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            frequency: Frequency ('d'=daily, 'w'=weekly, 'm'=monthly, '5'/'15'/'30'/'60'=minutes)
            adjust_flag: Adjust flag ('1'=forward, '2'=backward, '3'=none)
            fields: Optional field list

        Returns:
            pd.DataFrame: K-line data
        """
        pass

    @abstractmethod
    def get_stock_basic_info(self, code: str) -> pd.DataFrame:
        """
        Get stock basic information

        Args:
            code: Stock code

        Returns:
            pd.DataFrame: Stock basic information
        """
        pass

    @abstractmethod
    def get_dividend_data(self,
                          code: str,
                          year: str,
                          year_type: str = 'report') -> pd.DataFrame:
        """Get dividend information"""
        pass

    @abstractmethod
    def get_adjust_factor_data(self, code: str, start_date: str,
                               end_date: str) -> pd.DataFrame:
        """Get adjustment factor data"""
        pass

    @abstractmethod
    def get_financial_data(self, code: str, year: str, quarter: int,
                           data_types: List[str]) -> Dict[str, pd.DataFrame]:
        """Get financial data for multiple categories in one call

        Returns:
            Dict[str, pd.DataFrame]: mapping data types to their DataFrames
        """
        pass

    @abstractmethod
    def get_report(self,
                   code: str,
                   start_date: str,
                   end_date: str,
                   report_type: str = 'performance_express') -> pd.DataFrame:
        """Get report data (performance express/forecast)"""
        pass

    @abstractmethod
    def get_stock_industry(self, code: str, date: str) -> pd.DataFrame:
        """Get industry classification"""
        pass

    @abstractmethod
    def get_stock_list(self, date: str, data_type: str = '') -> pd.DataFrame:
        """Get stock list or index constituents"""
        pass

    @abstractmethod
    def get_trade_dates(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Get trading calendar"""
        pass

    @abstractmethod
    def get_macro_data(
        self,
        start_date: str,
        end_date: str,
        data_types: Optional[List[str]] = None,
        extra_kwargs: Optional[Dict[str,
                                    Any]] = None) -> Dict[str, pd.DataFrame]:
        """Get macroeconomic data for multiple categories in one call"""
        pass

    def get_extra_tools(self) -> Dict[str, Any]:
        """Get extra tools for the data source"""
        return {}
