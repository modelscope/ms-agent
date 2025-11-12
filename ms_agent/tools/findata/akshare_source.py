# Copyright (c) Alibaba, Inc. and its affiliates.
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from ms_agent.tools.findata.data_source_base import (DataSourceError,
                                                     FinancialDataSource,
                                                     NoDataFoundError)
from ms_agent.utils import get_logger
from ms_agent.utils.utils import install_package

logger = get_logger()


class AKShareDataSource(FinancialDataSource):
    """
    AKShare Data Source Implementation

    Supports multi-market data:
    - A-share market data
    - HK stock market data
    - US stock market data

    Note: Some BaoStock-specific features are not supported by AKShare.
    """

    def __init__(self):
        logger.info('Installing AKShare package...')
        try:
            install_package(package_name='akshare')
        except Exception as e:
            raise e

        global akshare
        import akshare

        logger.info('Initializing AKShare data source')
        try:
            # Test AKShare availability
            akshare.tool_trade_date_hist_sina()
            logger.info('AKShare initialized successfully')
        except Exception as e:
            raise DataSourceError(f'Failed to initialize AKShare: {e}')

    def _convert_code(self, code: str, market: str) -> str:
        """Convert code to AKShare symbol for a given market.

        - A-share: input like sh.600000/sz.000001 -> 600000/000001 for functions expecting plain digits
        - HK: allow raw digits like 00700/09988 or hk.00700/hk.09988
        - US: letters like AAPL/TSLA remain unchanged
        """
        if market == 'A':
            if code.startswith('sh.') or code.startswith('sz.'):
                return code.split('.')[1]
            return code
        elif market == 'HK':
            if code.startswith('hk.'):
                return code.split('.')[1]
            return code
        elif market == 'US':
            if code.startswith('us.'):
                return code.split('.')[1]
            return code.upper()
        return code

    def _convert_date(self, date: str) -> str:
        """Convert date to AKShare format"""
        return date.replace('-', '')

    def _standardize_columns(self, df: pd.DataFrame,
                             code: str) -> pd.DataFrame:
        """Standardize column names for compatibility with BaoStock format"""
        if df.empty:
            return df

        # Ensure code column exists
        if 'code' not in df.columns:
            if 'symbol' in df.columns:
                df['code'] = df['symbol']
            else:
                df['code'] = code

        # Standardize date column
        if 'date' not in df.columns:
            for col in ['日期', 'trade_date', 'datetime']:
                if col in df.columns:
                    df['date'] = df[col]
                    break

        # Standardize price columns
        column_mapping = {
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'pctChg',
        }

        for chinese, english in column_mapping.items():
            if chinese in df.columns and english not in df.columns:
                df[english] = df[chinese]

        return df

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
        logger.info(f'Fetching K-data for {code} ({start_date} to {end_date})')

        try:
            # AKShare adjust parameter mapping
            adjust_map = {
                '1': 'hfq',  # Backward adjust
                '2': 'qfq',  # Forward adjust
                '3': '',  # No adjust
            }
            adjust = adjust_map.get(adjust_flag, '')

            period_map = {
                'd': 'daily',
                'w': 'weekly',
                'm': 'monthly',
                '5': None,
                '15': None,
                '30': None,
                '60': None,
            }
            period = period_map.get(frequency, 'daily')

            # Minute-level data not supported by AKShare
            if period is None:
                raise DataSourceError(
                    f'Minute-level frequency "{frequency}" is not supported by AKShare. '
                    f'Please use BaoStock or Hybrid source for minute-level data.'
                )

            st_date = self._convert_date(start_date)
            ed_date = self._convert_date(end_date)

            # Route by market heuristics
            if code.startswith('sh.') or code.startswith(
                    'sz.') or code.startswith('bj'):
                clean_code = self._convert_code(code, market='A')
                df = akshare.stock_zh_a_hist(
                    symbol=clean_code,
                    period=period,
                    start_date=st_date,
                    end_date=ed_date,
                    adjust=adjust)
            elif code.startswith('hk'):
                clean_code = self._convert_code(code, market='HK')
                df = akshare.stock_hk_hist(
                    symbol=clean_code,
                    period=period,
                    start_date=st_date,
                    end_date=ed_date,
                    adjust=adjust)
            else:
                clean_code = self._convert_code(code, market='US')
                df = akshare.stock_us_hist(
                    symbol=clean_code,
                    period=period,
                    start_date=st_date,
                    end_date=ed_date,
                    adjust=adjust)

            if df.empty:
                raise NoDataFoundError(f'No K-data found for {code}')

            # Standardize column names
            df = self._standardize_columns(df, code)
            if 'adjustflag' not in df.columns:
                df['adjustflag'] = adjust_map.get(adjust_flag, '')

            return df

        except Exception as e:
            raise DataSourceError(f'Failed to fetch K-data: {e}')

    def get_stock_basic_info(self, code: str) -> pd.DataFrame:
        """Get stock basic information"""
        logger.info(f'Fetching basic info for {code}')

        try:
            if code.startswith('hk'):
                return self._get_hk_basic_info(code)
            elif code.startswith('us'):
                return self._get_us_basic_info(code)
            else:
                return self._get_a_share_basic_info(code)

        except (NoDataFoundError, DataSourceError):
            # Re-raise custom errors without wrapping
            raise
        except Exception as e:
            # Only wrap unexpected errors
            raise DataSourceError(f'Failed to fetch basic info: {e}')

    def _get_hk_basic_info(self, code: str) -> pd.DataFrame:
        """Get HK stock basic information"""
        clean_code = self._convert_code(code, market='HK')
        df_stock_info = pd.DataFrame()
        df_business_info = pd.DataFrame()

        # Try to fetch base info
        try:
            df_base_info = akshare.stock_hk_spot_em()
            stock_info = df_base_info[df_base_info['代码'] == clean_code]
            if not stock_info.empty:
                df_stock_info = pd.DataFrame({
                    'code': [code],
                    'code_name': [stock_info['名称'].iloc[0]],
                    'listingDate': [''],  # listing date might not be available
                    'outDate': [''],
                    'type': ['2'],  # type of stock
                    'status': ['1']
                })
        except Exception:
            logger.warning(f'Failed to fetch HK stock base info for {code}')

        # Try to fetch business info
        try:
            df_business_info = akshare.stock_zyjs_ths(symbol=clean_code)
            if not df_business_info.empty:
                df_business_info = df_business_info.rename(
                    columns={
                        '公司名称': 'company name',
                        '英文名称': 'english name',
                        '注册地': 'place of incorporation',
                        '注册地址': 'registered address',
                        '公司成立日期': 'date of incorporation',
                        '所属行业': 'industry',
                        '董事长': 'chairman',
                        '公司秘书': 'company secretary',
                        '员工人数': 'number of employees',
                        '办公地址': 'office address',
                        '公司网址': 'website',
                        'E-MAIL': 'email',
                        '年结日': 'financial year end',
                        '联系电话': 'contact number',
                        '核数师': 'auditor',
                        '传真': 'fax',
                        '公司介绍': 'company description'
                    })
        except Exception:
            logger.warning(
                f'Failed to fetch HK stock business info for {code}')

        if df_stock_info.empty and df_business_info.empty:
            raise NoDataFoundError(f'No basic info found for {code}')

        return pd.concat([df_stock_info, df_business_info], axis=1)

    def _get_us_basic_info(self, code: str) -> pd.DataFrame:
        """Get US stock basic information"""
        symbol = self._convert_code(code, 'US')

        try:
            df = akshare.stock_us_spot_em()
            stock_info = df[df['代码'] == symbol]

            if stock_info.empty:
                raise NoDataFoundError(
                    f'No US stock basic info found for {code}')

            result_df = pd.DataFrame({
                'code': [code],
                'code_name': [stock_info['名称'].iloc[0]],
                'listingDate': [''],
                'outDate': [''],
                'type': ['3'],
                'status': ['1']
            })

            return result_df

        except Exception as e:
            raise DataSourceError(
                f'Error fetching US stock basic info for {code}: {e}')

    def _get_a_share_basic_info(self, code: str) -> pd.DataFrame:
        """Get A-share stock basic information"""
        clean_code = self._convert_code(code, 'A')

        try:
            df_base_info = akshare.stock_individual_info_em(symbol=clean_code)

            if df_base_info.empty:
                raise NoDataFoundError(f'No basic info found for {code}')

            result_df = pd.DataFrame({
                'code': [code],
                'code_name': [
                    df_base_info.loc[df_base_info['item'] == '股票简称',
                                     'value'].iloc[0]
                    if not df_base_info.loc[df_base_info['item'] == '股票简称',
                                            'value'].empty else ''
                ],
                'listingDate': [
                    df_base_info.loc[df_base_info['item'] == '上市时间',
                                     'value'].iloc[0]
                    if not df_base_info.loc[df_base_info['item'] == '上市时间',
                                            'value'].empty else ''
                ],
                'outDate': [''],
                'type': ['1'],
                'status': ['1']
            })

            df_business_info = akshare.stock_zyjs_ths(symbol=clean_code)
            if df_business_info.empty:
                raise NoDataFoundError(f'No business info found for {code}')

            df_business_info = df_business_info.rename(
                columns={
                    '股票代码': 'stock code',
                    '主营业务': 'main business',
                    '产品类型': 'product type',
                    '产品名称': 'product name',
                    '经营范围': 'business scope'
                })

            return pd.concat([result_df, df_business_info], axis=1)

        except Exception as e:
            raise DataSourceError(
                f'Error fetching A-share basic info for {code}: {e}')

    def get_dividend_data(self,
                          code: str,
                          year: Optional[str] = None,
                          year_type: str = 'report') -> pd.DataFrame:
        """Dividend info is not provided via a unified endpoint across markets in AKShare."""
        raise DataSourceError(
            'get_dividend_data is not supported by AKShareDataSource; use BaoStock or Hybrid'
        )

    def get_adjust_factor_data(self, code: str, start_date: str,
                               end_date: str) -> pd.DataFrame:
        """Adjust factor via AKShare varies by function; not standardized here."""
        raise DataSourceError(
            'get_adjust_factor_data is not supported by AKShareDataSource; use BaoStock or Hybrid'
        )

    def get_financial_data(self, code: str, year: str, quarter: int,
                           data_types: List[str]) -> dict:
        """
        Get financial data for multiple categories in one call.
        """
        logger.info(
            f'Fetching financial data for {code} ({year}Q{quarter}) {data_types}'
        )

        if code.startswith(('hk.', 'us.')):
            logger.warning(
                'For U.S. and Hong Kong stocks, only a single complete financial indicators table is '
                'currently supported, covering all data types.')
            clean_code = self._convert_code(
                code, market='HK' if code.startswith('hk.') else 'US')
        elif code.startswith(('sh.', 'sz.', 'bj.')):
            clean_code = self._convert_code(code, market='A')
        else:
            clean_code = code

        def _q_end(y: str, q: int) -> str:
            y = str(y)
            if q == 1:
                return f'{y}-03-31'
            if q == 2:
                return f'{y}-06-30'
            if q == 3:
                return f'{y}-09-30'
            if q == 4:
                return f'{y}-12-31'
            raise ValueError(f'Invalid quarter: {q}')

        Q_NAME = {1: '一季报', 2: '中报', 3: '三季报', 4: '年报'}
        target_date = _q_end(year, quarter)
        target_qname = Q_NAME[quarter]

        def _select_row_by_report(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df
            d = df.copy()

            # convert REPORT_DATE to date
            if 'REPORT_DATE' in d.columns:
                d['_dt'] = pd.to_datetime(
                    d['REPORT_DATE']).dt.date.astype('str')
                hit = d[d['_dt'] == target_date]
                if not hit.empty:
                    return hit.drop(columns=['_dt'])

            # match report period name (中报/一季报/三季报/年报)
            for col in ('REPORT_DATE_NAME', 'REPORT_TYPE'):
                if col in d.columns:
                    hit = d[d[col].astype(str).str.contains(str(year))
                            & d[col].astype(str).str.contains(target_qname)]
                    if not hit.empty:
                        return hit

            # Fallback: Select the row closest to the target_date
            if 'REPORT_DATE' in d.columns:
                d['_dt'] = pd.to_datetime(
                    d['REPORT_DATE']).dt.date.astype('str')
                d['_diff'] = (pd.to_datetime(d['_dt'])
                              - pd.to_datetime(target_date)).abs()
                d = d.sort_values('_diff')
                return d.drop(columns=['_dt', '_diff']).head(1)

            return d.head(1)

        META_KEEP = [
            'REPORT_DATE', 'REPORT_TYPE', 'REPORT_DATE_NAME', 'NOTICE_DATE',
            'UPDATE_DATE'
        ]

        def _filter_columns(row_df: pd.DataFrame,
                            category: str) -> pd.DataFrame:
            if row_df.empty:
                return row_df
            cols = list(row_df.columns)

            # Mapping from categories to "field name patterns"
            PATTERNS = {
                'profit': [
                    r'^(EPS|EPS.*|BPS|MGZBGJ|MGWFPLR|MGJYXJJE)$',  # Per-share indicators
                    r'^(ROE|ROEJQ|ROEKCJQ|ROIC|ROA).*$',  # Profitability ratios: ROE / ROIC / ROA
                    r'^(MLR|XSJLL|GROSS|NET_INTEREST_MARGIN)$',
                    # Gross margin / Net profit margin / Net interest margin
                    r'^(PARENTNETPROFIT|NET_PROFIT|NETPROFIT)$',  # Net profit attributable to parent / Net profit
                    r'^(TOTALOPERATEREVE|TOI|REVENUE|PER_TOI)$',  # Total operating revenue / Total income
                ],
                'operation': [
                    r'^(YSZKZZL|YSZKZZTS)$',  # Accounts receivable turnover ratio / days
                    r'^(CHZZL|CHZZTS)$',  # Inventory turnover ratio / days
                    r'^(TOAZZL|ZZCZZTS)$',  # Total asset turnover ratio / days
                    r'^(LDZC.*ZZL|LDZC.*ZZTS)$',  # Current asset turnover ratio (if available)
                    r'.*TURN.*',  # Fallback for any other *TURN* pattern
                ],
                'growth': [
                    r'.*(YOY|_TZ|_TB)$',  # Year-over-year indicators: *_YOY / *_TZ / *_TB
                    r'^(TOTALOPERATEREVETZ|PARENTNETPROFITTZ|EPSJBTZ)$',  # YoY growth of revenue / net profit / EPS
                    r'^(ROE.*TZ|ROIC.*TZ)$',  # YoY growth of ROE / ROIC
                ],
                'dupont': [
                    r'^(ROEJQ)$',  # ROE (Return on Equity)
                    r'^(TOAZZL)$',  # Asset turnover ratio
                    r'^(XSJLL)$',  # Net profit margin (computed if missing)
                    # Possible item: Equity Multiplier.
                ],
            }

            keep = set(
                c for c in cols if any(
                    re.match(p, c) for p in PATTERNS[category]))
            keep |= set(c for c in META_KEEP if c in cols)

            out = row_df.loc[:,
                             [c for c in row_df.columns if c in keep]].copy()

            # Dupont net profit margin fallback calculation: PARENTNETPROFIT / TOTALOPERATEREVE
            if category == 'dupont' and 'XSJLL' not in out.columns:
                base_cols = set(['PARENTNETPROFIT', 'TOTALOPERATEREVE'])
                if base_cols.issubset(set(row_df.columns)):
                    try:
                        val = float(row_df.iloc[0]['PARENTNETPROFIT'])
                        den = float(row_df.iloc[0]['TOTALOPERATEREVE'])
                        out['XSJLL_calc'] = (val / den) if den else pd.NA
                    except Exception as e:
                        logger.warning(
                            f'Failed to calculate XSJLL_calc for {code}: {e}')
                        out['XSJLL_calc'] = pd.NA

            out.insert(0, 'code', code)
            return out

        result: dict = {}
        ind_df = pd.DataFrame()
        if code.startswith(('hk.', 'us.')):
            try:
                ind_df = akshare.stock_financial_hk_analysis_indicator_em(
                    symbol=clean_code) if code.startswith('hk.') else \
                    akshare.stock_financial_us_analysis_indicator_em(symbol=clean_code)
                ind_df = _select_row_by_report(ind_df)
            except Exception as e:
                logger.warning(
                    f'Failed to fetch financial_hk_analysis_indicator_em or financial_us_analysis_indicator_em: {e}'
                )
            result['financial_indicators'] = ind_df

        elif code.startswith(('sh.', 'sz.', 'bj.')):
            needs_indicator = any(
                dt in ('profit', 'operation', 'growth', 'dupont')
                for dt in data_types)

            if needs_indicator:
                try:
                    ind_df = akshare.stock_financial_analysis_indicator(
                        symbol=clean_code)
                    ind_df = _select_row_by_report(ind_df)
                except Exception as e:
                    logger.warning(
                        f'Failed to fetch financial_analysis_indicator: {e}')
                    ind_df = pd.DataFrame()

            for data_type in data_types:
                try:
                    result[data_type] = pd.DataFrame()
                    if data_type in ('profit', 'operation', 'growth',
                                     'dupont'):
                        if ind_df.empty:
                            logger.warning(
                                f'No indicator row for {code} {year}Q{quarter}'
                            )
                            continue
                        result[data_type] = _filter_columns(ind_df, data_type)
                        continue

                    elif data_type == 'balance':
                        df = akshare.stock_balance_sheet_by_report_em(
                            symbol=code.replace('.', '').upper())
                        row = _select_row_by_report(df)
                        if not row.empty:
                            result[data_type] = row

                    elif data_type == 'cash_flow':
                        df = akshare.stock_cash_flow_sheet_by_report_em(
                            symbol=code.replace('.', '').upper())
                        row = _select_row_by_report(df)
                        if not row.empty:
                            result[data_type] = row

                    else:
                        logger.warning(f'Unsupported data type: {data_type}')
                        continue

                except Exception as e:
                    logger.warning(f'Failed to fetch {data_type} data: {e}')
                    continue

        if not result or all(df.empty for df in result.values()):
            raise NoDataFoundError(
                f'No financial data found for {code} ({year}Q{quarter})')

        return result

    def get_report(self,
                   code: str,
                   start_date: str,
                   end_date: str,
                   report_type: str = 'performance_express') -> pd.DataFrame:
        """Report data is not supported by AKShare."""
        raise DataSourceError(
            'get_report is not supported by AKShareDataSource; use BaoStock or Hybrid'
        )

    def get_stock_industry(self, code: str, date: str) -> pd.DataFrame:
        """Industry classification is not supported by AKShare."""
        raise DataSourceError(
            'get_stock_industry is not supported by AKShareDataSource; use BaoStock or Hybrid'
        )

    def get_stock_list(self,
                       date: str,
                       data_type: str = 'all_a_share') -> pd.DataFrame:
        """Get stock list (A-shares only, index constituents not supported)."""
        logger.info(
            f'Fetching stock list for {data_type}, only support a_share and latest data'
        )

        try:
            if data_type == 'sse50':
                df = akshare.index_stock_cons(symbol='000016')
            elif data_type == 'hs300':
                df = akshare.index_stock_cons(symbol='000300')
            elif data_type == 'zz500':
                df = akshare.index_stock_cons(symbol='000905')
            elif data_type == 'all_a_share':
                df_a_share = akshare.stock_zh_a_spot_em()
                df_a_share['market'] = 'A'
                df = df_a_share[['代码', '名称', 'market']].copy()
                df = df.rename(columns={'代码': 'code', '名称': 'code_name'})

            return df

        except Exception as e:
            raise DataSourceError(f'Failed to fetch stock list: {e}')

    def get_trade_dates(self,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> pd.DataFrame:
        """Get trading calendar"""
        logger.info(f'Fetching trade dates ({start_date} to {end_date})')

        try:
            df = akshare.tool_trade_date_hist_sina()

            # Ensure trade_date is string for comparison
            if 'trade_date' in df.columns:
                df['trade_date'] = df['trade_date'].astype(str)

            if start_date:
                df = df[df['trade_date'] >= start_date]
            if end_date:
                df = df[df['trade_date'] <= end_date]

            return df

        except Exception as e:
            raise DataSourceError(f'Failed to fetch trade dates: {e}')

    def get_macro_data(
        self,
        start_date: str,
        end_date: str,
        data_types: Optional[List[str]] = None,
        extra_kwargs: Optional[Dict[str,
                                    Any]] = None) -> Dict[str, pd.DataFrame]:
        """Macroeconomic data."""
        if data_types is None:
            data_types = []
        if extra_kwargs is None:
            extra_kwargs = {}

        logger.info(
            f'Fetching macroeconomic data ({start_date} to {end_date}) {data_types}'
        )

        if not data_types:
            raise ValueError('data_types cannot be empty')

        result: dict = {}
        for data_type in data_types:
            try:
                if data_type in ('deposit_rate', 'loan_rate'):
                    result[data_type] = akshare.rate_interbank()
                elif data_type in ('required_reserve_ratio'):
                    raise DataSourceError(
                        'Required reserve ratio is not supported by AKShare')
                elif data_type == 'money_supply_year':
                    result[data_type] = self._get_money_supply_data_year(
                        start_date, end_date)
                elif data_type == 'money_supply_month':
                    result[data_type] = self._get_money_supply_data_month(
                        start_date, end_date)
                else:
                    raise ValueError(f'Invalid data type: {data_type}')

            except Exception as e:
                logger.warning(f'Failed to fetch {data_type} data: {e}')
                result[data_type] = pd.DataFrame()
                continue

        if not result:
            raise NoDataFoundError(
                'No macro data found for the specified criteria')
        return result

    def _get_money_supply_data_month(
            self,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None) -> pd.DataFrame:
        try:
            df = akshare.macro_china_money_supply()  # from 2008-01 to now
            df['月份'] = pd.to_datetime(df['月份'].str.replace('月份',
                                                           '').str.replace(
                                                               '年', '-'))
            df['月份'] = df['月份'].dt.to_period('M')
            if start_date:
                df = df[
                    df['月份'] >= pd.to_datetime(start_date).strftime('%Y-%m')]
            if end_date:
                df = df[df['月份'] <= pd.to_datetime(end_date).strftime('%Y-%m')]

            return df.sort_values('月份').reset_index(drop=True)
        except Exception as e:
            raise DataSourceError(
                f'Error fetching monthly money supply data: {e}')

    def _get_money_supply_data_year(
            self,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None) -> pd.DataFrame:
        month_df = self._get_money_supply_data_month()
        # Take the last issue of each year (usually December; if missing, take the last available entry of that year).
        month_df['年'] = month_df['月份'].dt.year
        last_in_year = (
            month_df.sort_values('月份').groupby(
                '年', as_index=False).tail(1).reset_index(drop=True))
        cols = [
            '货币和准货币(M2)-数量(亿元)',
            '货币和准货币(M2)-同比增长',
            '货币(M1)-数量(亿元)',
            '货币(M1)-同比增长',
            '流通中的现金(M0)-数量(亿元)',
            '流通中的现金(M0)-同比增长',
        ]
        year_df = last_in_year[
            ['年'] + [c for c in cols if c in last_in_year.columns]]

        if start_date:
            year_df = year_df[year_df['年'] >= pd.to_datetime(start_date).year]
        if end_date:
            year_df = year_df[year_df['年'] <= pd.to_datetime(end_date).year]

        return year_df.sort_values('年').reset_index(drop=True)
