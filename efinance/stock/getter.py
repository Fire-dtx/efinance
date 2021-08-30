from datetime import datetime, timedelta
from ..utils import process_dataframe_and_series
import rich
from jsonpath import jsonpath
from retry import retry
import pandas as pd
import requests
import multitasking
import signal
from tqdm import tqdm
from typing import (Dict,
                    List,
                    Union)
from ..shared import session
from ..common import get_quote_history as get_quote_history_for_stock
from ..common import get_history_bill as get_history_bill_for_stock
from ..common import get_today_bill as get_today_bill_for_stock
from ..common import get_realtime_quotes_by_fs
from ..utils import (to_numeric,
                     get_quote_id)
from .config import EASTMONEY_STOCK_DAILY_BILL_BOARD_FIELDS, EASTMONEY_STOCK_BASE_INFO_FIELDS
from ..common.config import (
    FS_DICT,
    MARKET_NUMBER_DICT,
    EASTMONEY_REQUEST_HEADERS,
    EASTMONEY_QUOTE_FIELDS
)

signal.signal(signal.SIGINT, multitasking.killall)


@to_numeric
def get_base_info_single(stock_code: str) -> pd.Series:
    """
    获取单股票基本信息

    Parameters
    ----------
    stock_code : str
        股票代码

    Returns
    -------
    Series
        单只股票基本信息

    """
    fields = ",".join(EASTMONEY_STOCK_BASE_INFO_FIELDS.keys())
    params = (
        ('ut', 'fa5fd1943c7b386f172d6893dbfba10b'),
        ('invt', '2'),
        ('fltt', '2'),
        ('fields', fields),
        ('secid', get_quote_id(stock_code)),

    )
    url = 'http://push2.eastmoney.com/api/qt/stock/get'
    json_response = session.get(url,
                                headers=EASTMONEY_REQUEST_HEADERS,
                                params=params).json()

    s = pd.Series(json_response['data']).rename(
        index=EASTMONEY_STOCK_BASE_INFO_FIELDS)
    return s[EASTMONEY_STOCK_BASE_INFO_FIELDS.values()]


def get_base_info_muliti(stock_codes: List[str]) -> pd.DataFrame:
    """
    获取股票多只基本信息

    Parameters
    ----------
    stock_codes : List[str]
        股票代码列表

    Returns
    -------
    DataFrame
        多只股票基本信息
    """

    @multitasking.task
    @retry(tries=3, delay=1)
    def start(stock_code: str):
        s = get_base_info_single(stock_code)
        dfs.append(s)
        pbar.update()
        pbar.set_description(f'Processing => {stock_code}')
    dfs: List[pd.DataFrame] = []
    pbar = tqdm(total=len(stock_codes))
    for stock_code in stock_codes:
        start(stock_code)
    multitasking.wait_for_tasks()
    df = pd.DataFrame(dfs)
    return df


@to_numeric
def get_base_info(stock_codes: Union[str, List[str]]) -> Union[pd.Series, pd.DataFrame]:
    """
    Parameters
    ----------
    stock_codes : Union[str, List[str]]
        股票代码或股票代码构成的列表

    Returns
    -------
    Union[Series, DataFrame]

        - ``Series`` : 包含单只股票基本信息(当 ``stock_codes`` 是字符串时)
        - ``DataFrane`` : 包含多只股票基本信息(当 ``stock_codes`` 是字符串列表时)

    Raises
    ------
    TypeError
        当 ``stock_codes`` 类型不符合要求时

    Examples
    --------
    >>> import efinance as ef
    >>> # 获取单只股票信息
    >>> ef.stock.get_base_info('600519')
    股票代码                  600519
    股票名称                    贵州茅台
    市盈率(动)                 39.38
    市净率                    12.54
    所处行业                    酿酒行业
    总市值          2198082348462.0
    流通市值         2198082348462.0
    板块编号                  BK0477
    ROE                     8.29
    净利率                  54.1678
    净利润       13954462085.610001
    毛利率                  91.6763
    dtype: object

    >>> # 获取多只股票信息
    >>> ef.stock.get_base_info(['600519','300715'])
        股票代码  股票名称  市盈率(动)    市净率  所处行业           总市值          流通市值    板块编号   ROE      净利率           净利润      毛利率
    0  300715  凯伦股份   42.29   3.12  水泥建材  9.160864e+09  6.397043e+09  BK0424  3.97  12.1659  5.415488e+07  32.8765
    1  600519  贵州茅台   39.38  12.54  酿酒行业  2.198082e+12  2.198082e+12  BK0477  8.29  54.1678  1.395446e+10  91.6763

    """

    if isinstance(stock_codes, str):
        return get_base_info_single(stock_codes)
    elif hasattr(stock_codes, '__iter__'):
        return get_base_info_muliti(stock_codes)

    raise TypeError(f'所给的 {stock_codes} 不符合参数要求')


def get_quote_history(stock_codes: Union[str, List[str]],
                      beg: str = '19000101',
                      end: str = '20500101',
                      klt: int = 101,
                      fqt: int = 1) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    获取股票的 K 线数据

    Parameters
    ----------
    stock_codes : Union[str,List[str]]
        股票代码、名称 或者 股票代码、名称构成的列表
    beg : str, optional
        开始日期，默认为 ``'19000101'`` ，表示 1900年1月1日
    end : str, optional
        结束日期，默认为 ``'20500101'`` ，表示 2050年1月1日
    klt : int, optional
        行情之间的时间间隔，默认为 ``101`` ，可选示例如下

        - ``1`` : 分钟
        - ``5`` : 5 分钟
        - ``15`` : 15 分钟
        - ``30`` : 30 分钟
        - ``60`` : 60 分钟
        - ``101`` : 日
        - ``102`` : 周
        - ``103`` : 月

    fqt : int, optional
        复权方式，默认为 ``1`` ，可选示例如下

        - ``0`` : 不复权
        - ``1`` : 前复权
        - ``2`` : 后复权

    Returns
    -------
    Union[DataFrame, Dict[str, DataFrame]]
        股票的 K 线数据

        - ``DataFrame`` : 当 ``stock_codes`` 是 ``str`` 时
        - ``Dict[str, DataFrame]`` : 当 ``stock_codes`` 是 ``List[str]`` 时

    Examples
    --------
    >>> import efinance as ef
    >>> # 获取单只股票日 K 行情数据
    >>> ef.stock.get_quote_history('600519')
        股票名称    股票代码          日期       开盘       收盘       最高       最低     成交量           成交额    振幅   涨跌幅    涨跌额    换手率
    0     贵州茅台  600519  2001-08-27   -89.74   -89.53   -89.08   -90.07  406318  1.410347e+09 -1.10  0.92   0.83  56.83
    1     贵州茅台  600519  2001-08-28   -89.64   -89.27   -89.24   -89.72  129647  4.634630e+08 -0.54  0.29   0.26  18.13
    2     贵州茅台  600519  2001-08-29   -89.24   -89.36   -89.24   -89.42   53252  1.946890e+08 -0.20 -0.10  -0.09   7.45
    3     贵州茅台  600519  2001-08-30   -89.38   -89.22   -89.14   -89.44   48013  1.775580e+08 -0.34  0.16   0.14   6.72
    4     贵州茅台  600519  2001-08-31   -89.21   -89.24   -89.12   -89.28   23231  8.623100e+07 -0.18 -0.02  -0.02   3.25
    ...    ...     ...         ...      ...      ...      ...      ...     ...           ...   ...   ...    ...    ...
    4756  贵州茅台  600519  2021-07-23  1937.82  1900.00  1937.82  1895.09   47585  9.057762e+09  2.20 -2.06 -40.01   0.38
    4757  贵州茅台  600519  2021-07-26  1879.00  1804.11  1879.00  1780.00   98619  1.789436e+10  5.21 -5.05 -95.89   0.79
    4758  贵州茅台  600519  2021-07-27  1803.00  1712.89  1810.00  1703.00   86577  1.523081e+10  5.93 -5.06 -91.22   0.69
    4759  贵州茅台  600519  2021-07-28  1703.00  1768.90  1788.20  1682.12   85369  1.479247e+10  6.19  3.27  56.01   0.68
    4760  贵州茅台  600519  2021-07-29  1810.01  1749.79  1823.00  1734.34   63864  1.129957e+10  5.01 -1.08 -19.11   0.51

    >>> # 获取多只股票历史行情
    >>> stock_df = ef.stock.get_quote_history(['600519','300750'])
    >>> type(stock_df)
    <class 'dict'>
    >>> stock_df.keys()
    dict_keys(['300750', '600519'])
    >>> stock_df['600519']
        股票名称    股票代码          日期       开盘       收盘       最高       最低     成交量           成交额    振幅   涨跌幅    涨跌额    换手率
    0     贵州茅台  600519  2001-08-27   -89.74   -89.53   -89.08   -90.07  406318  1.410347e+09 -1.10  0.92   0.83  56.83
    1     贵州茅台  600519  2001-08-28   -89.64   -89.27   -89.24   -89.72  129647  4.634630e+08 -0.54  0.29   0.26  18.13
    2     贵州茅台  600519  2001-08-29   -89.24   -89.36   -89.24   -89.42   53252  1.946890e+08 -0.20 -0.10  -0.09   7.45
    3     贵州茅台  600519  2001-08-30   -89.38   -89.22   -89.14   -89.44   48013  1.775580e+08 -0.34  0.16   0.14   6.72
    4     贵州茅台  600519  2001-08-31   -89.21   -89.24   -89.12   -89.28   23231  8.623100e+07 -0.18 -0.02  -0.02   3.25
    ...    ...     ...         ...      ...      ...      ...      ...     ...           ...   ...   ...    ...    ...
    4756  贵州茅台  600519  2021-07-23  1937.82  1900.00  1937.82  1895.09   47585  9.057762e+09  2.20 -2.06 -40.01   0.38
    4757  贵州茅台  600519  2021-07-26  1879.00  1804.11  1879.00  1780.00   98619  1.789436e+10  5.21 -5.05 -95.89   0.79
    4758  贵州茅台  600519  2021-07-27  1803.00  1712.89  1810.00  1703.00   86577  1.523081e+10  5.93 -5.06 -91.22   0.69
    4759  贵州茅台  600519  2021-07-28  1703.00  1768.90  1788.20  1682.12   85369  1.479247e+10  6.19  3.27  56.01   0.68
    4760  贵州茅台  600519  2021-07-29  1810.01  1749.79  1823.00  1734.34   63864  1.129957e+10  5.01 -1.08 -19.11   0.51

    """
    df = get_quote_history_for_stock(
        stock_codes,
        beg=beg,
        end=end,
        klt=klt,
        fqt=fqt

    )
    if isinstance(df, pd.DataFrame):

        df.rename(columns={'代码': '股票代码',
                           '名称': '股票名称'
                           },
                  inplace=True)
    elif isinstance(df, dict):
        for stock_code in df.keys():
            df[stock_code].rename(columns={'代码': '股票代码',
                                           '名称': '股票名称'
                                           },
                                  inplace=True)

    return df


@process_dataframe_and_series(remove_columns_and_indexes=['市场编号'])
@to_numeric
def get_realtime_quotes() -> pd.DataFrame:
    """
    获取沪深市场最新行情总体情况

    Returns
    -------
    DataFrame
        沪深全市场A股上市公司的最新行情信息（涨跌幅、换手率等信息）

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_realtime_quotes()
            股票代码   股票名称     涨跌幅     最新价      最高      最低      今开     涨跌额    换手率    量比    动态市盈率     成交量           成交额   昨日收盘           总市值         流通市值      行情ID 市场类型
    0     688787    N海天  277.59  139.48  172.39  139.25  171.66  102.54  85.62     -    78.93   74519  1110318832.0  36.94    5969744000   1213908667  1.688787   沪A
    1     301045    N天禄  149.34   39.42   48.95    39.2   48.95   23.61  66.66     -    37.81  163061   683878656.0  15.81    4066344240    964237089  0.301045   深A
    2     300532   今天国际   20.04   12.16   12.16   10.69   10.69    2.03   8.85  3.02   -22.72  144795   171535181.0  10.13    3322510580   1989333440  0.300532   深A
    3     300600   国瑞科技   20.02   13.19   13.19   11.11   11.41     2.2  18.61  2.82   218.75  423779   541164432.0  10.99    3915421427   3003665117  0.300600   深A
    4     300985   致远新能   20.01   47.08   47.08    36.8    39.4    7.85  66.65  2.17    58.37  210697   897370992.0  39.23    6277336472   1488300116  0.300985   深A
    ...      ...    ...     ...     ...     ...     ...     ...     ...    ...   ...      ...     ...           ...    ...           ...          ...       ...  ...
    4598  603186   华正新材   -10.0   43.27   44.09   43.27   43.99   -4.81   1.98  0.48    25.24   27697   120486294.0  48.08    6146300650   6063519472  1.603186   沪A
    4599  688185  康希诺-U  -10.11   476.4  534.94  460.13   530.0   -53.6   6.02  2.74 -2088.07   40239  1960540832.0  530.0  117885131884  31831479215  1.688185   沪A
    4600  688148   芳源股份  -10.57    31.3   34.39    31.3    33.9    -3.7  26.07  0.56   220.01  188415   620632512.0   35.0   15923562000   2261706043  1.688148   沪A
    4601  300034   钢研高纳  -10.96   43.12   46.81   42.88    46.5   -5.31   7.45  1.77    59.49  323226  1441101824.0  48.43   20959281094  18706911861  0.300034   深A
    4602  300712   永福股份  -13.71    96.9  110.94    95.4   109.0   -15.4   6.96  1.26   511.21  126705  1265152928.0  112.3   17645877600  17645877600  0.300712   深A
    """
    fs = FS_DICT['stock']
    df = get_realtime_quotes_by_fs(fs)
    df.rename(columns={'代码': '股票代码',
                       '名称': '股票名称'
                       }, inplace=True)

    return df


@to_numeric
def get_history_bill(stock_code: str) -> pd.DataFrame:
    """
    获取单只股票历史单子流入流出数据

    Parameters
    ----------
    stock_code : str
        股票代码

    Returns
    -------
    DataFrame
        沪深市场单只股票历史单子流入流出数据

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_history_bill('600519')
        股票名称    股票代码          日期         主力净流入       小单净流入         中单净流入         大单净流入        超大单净流入  主力净流入占比  小单流入净占比  中单流入净占比  大单流入净占比  超大单流入净占比      收盘价   涨跌幅
    0    贵州茅台  600519  2021-03-04 -3.670272e+06  -2282056.0  5.952143e+06  1.461528e+09 -1.465199e+09    -0.03    -0.02     0.04    10.99    -11.02  2013.71 -5.05
    1    贵州茅台  600519  2021-03-05 -1.514880e+07  -1319066.0  1.646793e+07 -2.528896e+07  1.014016e+07    -0.12    -0.01     0.13    -0.19      0.08  2040.82  1.35
    2    贵州茅台  600519  2021-03-08 -8.001702e+08   -877074.0  8.010473e+08  5.670671e+08 -1.367237e+09    -6.29    -0.01     6.30     4.46    -10.75  1940.71 -4.91
    3    贵州茅台  600519  2021-03-09 -2.237770e+08  -6391767.0  2.301686e+08 -1.795013e+08 -4.427571e+07    -1.39    -0.04     1.43    -1.11     -0.27  1917.70 -1.19
    4    贵州茅台  600519  2021-03-10 -2.044173e+08  -1551798.0  2.059690e+08 -2.378506e+08  3.343331e+07    -2.02    -0.02     2.03    -2.35      0.33  1950.72  1.72
    ..    ...     ...         ...           ...         ...           ...           ...           ...      ...      ...      ...      ...       ...      ...   ...
    97   贵州茅台  600519  2021-07-26 -1.564233e+09  13142211.0  1.551091e+09 -1.270400e+08 -1.437193e+09    -8.74     0.07     8.67    -0.71     -8.03  1804.11 -5.05
    98   贵州茅台  600519  2021-07-27 -7.803296e+08 -10424715.0  7.907544e+08  6.725104e+07 -8.475807e+08    -5.12    -0.07     5.19     0.44     -5.56  1712.89 -5.06
    99   贵州茅台  600519  2021-07-28  3.997645e+08   2603511.0 -4.023677e+08  2.315648e+08  1.681997e+08     2.70     0.02    -2.72     1.57      1.14  1768.90  3.27
    100  贵州茅台  600519  2021-07-29 -9.209842e+08  -2312235.0  9.232964e+08 -3.959741e+08 -5.250101e+08    -8.15    -0.02     8.17    -3.50     -4.65  1749.79 -1.08
    101  贵州茅台  600519  2021-07-30 -1.524740e+09  -6020099.0  1.530761e+09  1.147248e+08 -1.639465e+09   -11.63    -0.05    11.68     0.88    -12.51  1678.99 -4.05

    """
    df = get_history_bill_for_stock(stock_code)
    df.rename(columns={
        '代码': '股票代码',
        '名称': '股票名称'
    }, inplace=True)
    return df


@to_numeric
def get_today_bill(stock_code: str) -> pd.DataFrame:
    """
    获取单只股票最新交易日的日内分钟级单子流入流出数据

    Parameters
    ----------
    stock_code : str
        股票代码

    Returns
    -------
    DataFrame
        单只股票最新交易日的日内分钟级单子流入流出数据

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_today_bill('600519')
        股票代码                时间        主力净流入      小单净流入        中单净流入        大单净流入       超大单净流入
    0    600519  2021-07-29 09:31   -3261705.0  -389320.0    3651025.0  -12529658.0    9267953.0
    1    600519  2021-07-29 09:32    6437999.0  -606994.0   -5831006.0  -42615994.0   49053993.0
    2    600519  2021-07-29 09:33   13179707.0  -606994.0  -12572715.0  -85059118.0   98238825.0
    3    600519  2021-07-29 09:34   15385244.0  -970615.0  -14414632.0  -86865209.0  102250453.0
    4    600519  2021-07-29 09:35    7853716.0  -970615.0   -6883104.0  -75692436.0   83546152.0
    ..      ...               ...          ...        ...          ...          ...          ...
    235  600519  2021-07-29 14:56 -918956019.0 -1299630.0  920255661.0 -397127393.0 -521828626.0
    236  600519  2021-07-29 14:57 -920977761.0 -2319213.0  923296987.0 -397014702.0 -523963059.0
    237  600519  2021-07-29 14:58 -920984196.0 -2312233.0  923296442.0 -395974137.0 -525010059.0
    238  600519  2021-07-29 14:59 -920984196.0 -2312233.0  923296442.0 -395974137.0 -525010059.0
    239  600519  2021-07-29 15:00 -920984196.0 -2312233.0  923296442.0 -395974137.0 -525010059.0

    """
    df = get_today_bill_for_stock(stock_code)
    df.rename(columns={
        '代码': '股票代码',
        '名称': '股票名称'
    }, inplace=True)
    return df


@to_numeric
def get_latest_quote(stock_codes: List[str]) -> pd.DataFrame:
    """
    获取沪深市场多只股票的实时涨幅情况

    Parameters
    ----------
    stock_codes : List[str]
        多只股票代码列表

    Returns
    -------
    DataFrame
        沪深市场、港股、美股多只股票的实时涨幅情况

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_latest_quote(['600519','300750'])
        股票代码  股票名称   涨跌幅      最新价      最高      最低      今开    涨跌额   换手率    量比   动态市盈率     成交量           成交额    昨日收盘            总市值           流通市值 市场类型
    0  600519  贵州茅台  0.59  1700.04  1713.0  1679.0  1690.0  10.04  0.30  0.72   43.31   37905  6.418413e+09  1690.0  2135586507912  2135586507912   沪A
    1  300750  宁德时代  0.01   502.05   529.9   480.0   480.0   0.05  1.37  1.75  149.57  277258  1.408545e+10   502.0  1169278366994  1019031580505   深A

    Notes
    -----
    当需要获取多只沪深 A 股 的实时涨跌情况时，最好使用 ``efinance.stock.get_realtime_quptes``

    """
    if isinstance(stock_codes, str):
        stock_codes = [stock_codes]
    secids: List[str] = [get_quote_id(stock_code)
                         for stock_code in stock_codes]

    columns = EASTMONEY_QUOTE_FIELDS
    fields = ",".join(columns.keys())
    params = (
        ('OSVersion', '14.3'),
        ('appVersion', '6.3.8'),
        ('fields', fields),
        ('fltt', '2'),
        ('plat', 'Iphone'),
        ('product', 'EFund'),
        ('secids', ",".join(secids)),
        ('serverVersion', '6.3.6'),
        ('version', '6.3.8'),
    )
    url = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
    json_response = session.get(url,
                                headers=EASTMONEY_REQUEST_HEADERS,
                                params=params).json()

    rows = jsonpath(json_response, '$..diff[:]')
    if rows is None:
        return pd.DataFrame(columns=columns.values()).rename({
            '市场编号': '市场类型'
        })

    df = pd.DataFrame(rows)[columns.keys()].rename(columns=columns)
    df['市场类型'] = df['市场编号'].apply(lambda x: MARKET_NUMBER_DICT.get(str(x)))
    del df['市场编号']
    return df


@to_numeric
def get_top10_stock_holder_info(stock_code: str,
                                top: int = 4) -> pd.DataFrame:
    """
    获取沪深市场指定股票前十大股东信息

    Parameters
    ----------
    stock_code : str
        股票代码
    top : int, optional
        最新 top 个前 10 大流通股东公开信息, 默认为  ``4``

    Returns
    -------
    DataFrame
        个股持仓占比前 10 的股东的一些信息

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_top10_stock_holder_info('600519',top = 1)
        股票代码        更新日期      股东代码                                股东名称     持股数    持股比例       增减     变动率
    0  600519  2021-03-31  80010298                  中国贵州茅台酒厂(集团)有限责任公司  6.783亿  54.00%       不变      --
    1  600519  2021-03-31  80637337                          香港中央结算有限公司   9594万   7.64%  -841.1万  -8.06%
    2  600519  2021-03-31  80732941                     贵州省国有资本运营有限责任公司   5700万   4.54%  -182.7万  -3.11%
    3  600519  2021-03-31  80010302                      贵州茅台酒厂集团技术开发公司   2781万   2.21%       不变      --
    4  600519  2021-03-31  80475097                      中央汇金资产管理有限责任公司   1079万   0.86%       不变      --
    5  600519  2021-03-31  80188285                        中国证券金融股份有限公司  803.9万   0.64%      -91   0.00%
    6  600519  2021-03-31  78043999      深圳市金汇荣盛财富管理有限公司-金汇荣盛三号私募证券投资基金  502.1万   0.40%       不变      --
    7  600519  2021-03-31  70400207  中国人寿保险股份有限公司-传统-普通保险产品-005L-CT001沪  434.1万   0.35%   44.72万  11.48%
    8  600519  2021-03-31    005827         中国银行股份有限公司-易方达蓝筹精选混合型证券投资基金    432万   0.34%       新进      --
    9  600519  2021-03-31  78083830      珠海市瑞丰汇邦资产管理有限公司-瑞丰汇邦三号私募证券投资基金  416.1万   0.33%       不变      --
    """

    def gen_fc(stock_code: str) -> str:
        """

        Parameters
        ----------
        stock_code : str
            股票代码

        Returns
        -------
        str
            指定格式的字符串
        """
        _type, stock_code = get_quote_id(stock_code).split('.')
        _type = int(_type)
        # 深市
        if _type == 0:
            return f'{stock_code}02'
        # 沪市
        return f'{stock_code}01'

    def get_public_dates(stock_code: str) -> List[str]:
        """
        获取指定股票公开股东信息的日期

        Parameters
        ----------
        stock_code : str
            股票代码

        Returns
        -------
        List[str]
            公开日期列表
        """

        quote_id = get_quote_id(stock_code)
        stock_code = quote_id.split('.')[-1]
        fc = gen_fc(stock_code)
        data = {"fc": fc}
        url = 'https://emh5.eastmoney.com/api/GuBenGuDong/GetFirstRequest2Data'
        json_response = requests.post(
            url,  json=data).json()
        dates = jsonpath(json_response, f'$..BaoGaoQi')
        if not dates:
            return []
        return dates

    fields = {
        'GuDongDaiMa': '股东代码',
        'GuDongMingCheng': '股东名称',
        'ChiGuShu': '持股数',
        'ChiGuBiLi': '持股比例',
        'ZengJian': '增减',
        'BianDongBiLi': '变动率',

    }
    quote_id = get_quote_id(stock_code)
    stock_code = quote_id.split('.')[-1]
    fc = gen_fc(stock_code)
    dates = get_public_dates(stock_code)
    dfs: List[pd.DataFrame] = []
    empty_df = pd.DataFrame(columns=['股票代码', '日期']+list(fields.values()))

    for date in dates[:top]:
        data = {"fc": fc, "BaoGaoQi": date}
        url = 'https://emh5.eastmoney.com/api/GuBenGuDong/GetShiDaLiuTongGuDong'
        response = requests.post(url, json=data)
        response.encoding = 'utf-8'
        items: List[dict] = jsonpath(
            response.json(), f'$..ShiDaLiuTongGuDongList[:]')
        if not items:
            continue
        df = pd.DataFrame(items)
        df.rename(columns=fields, inplace=True)
        df.insert(0, '股票代码', [stock_code for _ in range(len(df))])
        df.insert(1, '更新日期', [date for _ in range(len(df))])
        del df['IsLink']
        dfs.append(df)
    if len(dfs) == 0:
        return empty_df
    return pd.concat(dfs, axis=0, ignore_index=True)


def get_all_report_dates() -> pd.DataFrame:
    """
    获取沪深市场的全部股票报告期信息

    Returns
    -------
    DataFrame
        沪深市场的全部股票报告期信息

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_all_report_dates()
            报告日期       季报名称
    0   2021-06-30  2021年 半年报
    1   2021-03-31  2021年 一季报
    2   2020-12-31   2020年 年报
    3   2020-09-30  2020年 三季报
    4   2020-06-30  2020年 半年报
    5   2020-03-31  2020年 一季报
    6   2019-12-31   2019年 年报
    7   2019-09-30  2019年 三季报
    8   2019-06-30  2019年 半年报
    9   2019-03-31  2019年 一季报
    10  2018-12-31   2018年 年报
    11  2018-09-30  2018年 三季报
    12  2018-06-30  2018年 半年报
    13  2018-03-31  2018年 一季报
    14  2017-12-31   2017年 年报
    15  2017-09-30  2017年 三季报
    16  2017-06-30  2017年 半年报
    17  2017-03-31  2017年 一季报
    18  2016-12-31   2016年 年报
    19  2016-09-30  2016年 三季报
    20  2016-06-30  2016年 半年报
    21  2016-03-31  2016年 一季报
    22  2015-12-31   2015年 年报
    24  2015-06-30  2015年 半年报
    25  2015-03-31  2015年 一季报
    26  2014-12-31   2014年 年报
    27  2014-09-30  2014年 三季报
    28  2014-06-30  2014年 半年报
    29  2014-03-31  2014年 一季报
    30  2013-12-31   2013年 年报
    31  2013-09-30  2013年 三季报
    32  2013-06-30  2013年 半年报
    33  2013-03-31  2013年 一季报
    34  2012-12-31   2012年 年报
    35  2012-09-30  2012年 三季报
    36  2012-06-30  2012年 半年报
    37  2012-03-31  2012年 一季报
    38  2011-12-31   2011年 年报
    39  2011-09-30  2011年 三季报

    """
    fields = {
        'REPORT_DATE': '报告日期',
        'DATATYPE': '季报名称'
    }
    params = (
        ('type', 'RPT_LICO_FN_CPD_BBBQ'),
        ('sty', ','.join(fields.keys())),
        ('p', '1'),
        ('ps', '2000'),

    )
    url = 'https://datacenter.eastmoney.com/securities/api/data/get'
    response = requests.get(
        url,
        headers=EASTMONEY_REQUEST_HEADERS,
        params=params)
    items = jsonpath(response.json(), '$..data[:]')
    if not items:
        pd.DataFrame(columns=fields.values())
    df = pd.DataFrame(items)
    df = df.rename(columns=fields)
    df['报告日期'] = df['报告日期'].apply(lambda x: x.split()[0])
    return df


@to_numeric
def get_all_company_performance(date: str = None) -> pd.DataFrame:
    """
    获取沪深市场股票某一季度的表现情况

    Parameters
    ----------
    date : str, optional
        报告发布日期 部分可选示例如下(默认为 ``None``)

        - ``None`` : 最新季报
        - ``'2021-06-30'`` : 2021 年 Q2 季度报
        - ``'2021-03-31'`` : 2021 年 Q1 季度报

    Returns
    -------
    DataFrame
        获取沪深市场股票某一季度的表现情况

    Examples
    ---------
    >>> import efinance as ef
    >>> # 获取最新季度业绩表现
    >>> ef.stock.get_all_company_performance()
            股票代码  股票简称                 公告日期          营业收入   营业收入同比增长  营业收入季度环比           净利润     净利润同比增长   净利润季度环比    每股收益      每股净资产  净资产收益率      销售毛利率  每股经营现金流量
    0     688981  中芯国际  2021-08-28 00:00:00  1.609039e+10  22.253453   20.6593  5.241321e+09  278.100000  307.8042  0.6600  11.949525    5.20  26.665642  1.182556
    1     688819  天能股份  2021-08-28 00:00:00  1.625468e+10   9.343279   23.9092  6.719446e+08  -14.890000  -36.8779  0.7100  11.902912    6.15  17.323263 -1.562187
    2     688789  宏华数科  2021-08-28 00:00:00  4.555604e+08  56.418441    6.5505  1.076986e+08   49.360000   -7.3013  1.8900  14.926761   13.51  43.011243  1.421272
    3     688681  科汇股份  2021-08-28 00:00:00  1.503343e+08  17.706987  121.9407  1.664509e+07  -13.100000  383.3331  0.2100   5.232517    4.84  47.455511 -0.232395
    4     688670   金迪克  2021-08-28 00:00:00  3.209423e+07 -63.282413  -93.1788 -2.330505e+07 -242.275001 -240.1554 -0.3500   3.332254  -10.10  85.308531  1.050348
    ...      ...   ...                  ...           ...        ...       ...           ...         ...       ...     ...        ...     ...        ...       ...
    3720  600131  国网信通  2021-07-16 00:00:00  2.880378e+09   6.787087   69.5794  2.171389e+08   29.570000  296.2051  0.1800   4.063260    4.57  19.137437 -0.798689
    3721  600644  乐山电力  2021-07-15 00:00:00  1.257030e+09  18.079648    5.7300  8.379727e+07  -14.300000   25.0007  0.1556   3.112413    5.13  23.645137  0.200906
    3722  002261  拓维信息  2021-07-15 00:00:00  8.901777e+08  47.505282   24.0732  6.071063e+07   68.320000   30.0596  0.0550   2.351598    2.37  37.047968 -0.131873
    3723  601952  苏垦农发  2021-07-13 00:00:00  4.544138e+09  11.754570   47.8758  3.288132e+08    1.460000   83.1486  0.2400   3.888046    6.05  15.491684 -0.173772
    3724  601568  北元集团  2021-07-09 00:00:00  6.031506e+09  32.543303   30.6352  1.167989e+09   61.050000   40.8165  0.3200   3.541533    9.01  27.879243  0.389860

    >>> # 获取指定日期的季度业绩表现
    >>> ef.stock.get_all_company_performance('2020-03-31')
            股票代码  股票简称                 公告日期          营业收入  营业收入同比增长  营业收入季度环比           净利润     净利润同比增长  净利润季度环比    每股收益      每股净资产  净资产收益率      销售毛利率  每股经营现金流量
    0     605033  美邦股份  2021-08-25 00:00:00  2.178208e+08       NaN       NaN  4.319814e+07         NaN      NaN  0.4300        NaN     NaN  37.250416       NaN
    1     301048  金鹰重工  2021-07-30 00:00:00  9.165528e+07       NaN       NaN -2.189989e+07         NaN      NaN     NaN        NaN   -1.91  20.227118       NaN
    2     001213  中铁特货  2021-07-29 00:00:00  1.343454e+09       NaN       NaN -3.753634e+07         NaN      NaN -0.0100        NaN     NaN  -1.400708       NaN
    3     605588  冠石科技  2021-07-28 00:00:00  1.960175e+08       NaN       NaN  1.906751e+07         NaN      NaN  0.3500        NaN     NaN  16.324650       NaN
    4     688798  艾为电子  2021-07-27 00:00:00  2.469943e+08       NaN       NaN  2.707568e+07         NaN      NaN  0.3300        NaN    8.16  33.641934       NaN
    ...      ...   ...                  ...           ...       ...       ...           ...         ...      ...     ...        ...     ...        ...       ...
    4440  603186  华正新材  2020-04-09 00:00:00  4.117502e+08 -6.844813  -23.2633  1.763252e+07   18.870055 -26.3345  0.1400   5.878423    2.35  18.861255  0.094249
    4441  002838  道恩股份  2020-04-09 00:00:00  6.191659e+08 -8.019810  -16.5445  6.939886e+07   91.601624  76.7419  0.1700   2.840665    6.20  22.575224  0.186421
    4442  600396  金山股份  2020-04-08 00:00:00  2.023133e+09  0.518504   -3.0629  1.878432e+08  114.304022  61.2733  0.1275   1.511012    8.81  21.422393  0.085698
    4443  002913   奥士康  2020-04-08 00:00:00  4.898977e+08 -3.883035  -23.2268  2.524717e+07  -47.239162 -58.8136  0.1700  16.666749    1.03  22.470020  0.552624
    4444  002007  华兰生物  2020-04-08 00:00:00  6.775414e+08 -2.622289  -36.1714  2.472864e+08   -4.708821 -22.6345  0.1354   4.842456    3.71  61.408522  0.068341

    Notes
    -----
    当输入的日期不正确时，会输出可选的日期列表。
    你也可以通过函数 ``efinance.stock.get_all_report_dates`` 来获取可选日期

    """
    # TODO 加速
    fields = {
        'SECURITY_CODE': '股票代码',
        'SECURITY_NAME_ABBR': '股票简称',
        'NOTICE_DATE': '公告日期',
        'TOTAL_OPERATE_INCOME': '营业收入',
        'YSTZ': '营业收入同比增长',
        'YSHZ': '营业收入季度环比',
        'PARENT_NETPROFIT': '净利润',
        'SJLTZ': '净利润同比增长',
        'SJLHZ': '净利润季度环比',
        'BASIC_EPS': '每股收益',
        'BPS': '每股净资产',
        'WEIGHTAVG_ROE': '净资产收益率',
        'XSMLL': '销售毛利率',
        'MGJYXJJE': '每股经营现金流量'
        # 'ISNEW':'是否最新'
    }

    dates = get_all_report_dates()['报告日期'].to_list()
    if date is None:
        date = dates[0]
    if date not in dates:
        rich.print('日期输入有误，可选日期如下:')
        rich.print(dates)
        return pd.DataFrame(columns=fields.values())

    date = f"(REPORTDATE=\'{date}\')"
    page = 1
    dfs: List[pd.DataFrame] = []
    while 1:
        params = (
            ('type', 'RPT_LICO_FN_CPD_BB'),
            ('source', 'DataCenter'),
            ('sty', 'SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_MARKET,REPORTDATE,REPORTDATEWZ,REPORTDATEYW,BASIC_EPS,TOTAL_OPERATE_INCOME,TOTAL_OPERATE_INCOME_TQ,PARENT_NETPROFIT,PARENT_NETPROFIT_TQ,ISNEW,NOTICE_DATE'),
            ('p', f'{page}'),
            ('ps', '500'),
            ('sr', '-1,1'),
            ('st', 'NOTICE_DATE,SECURITY_CODE'),
            ('filter',
             f'{date}(TRADE_MARKET in (0101,0102,0201,0202,0120,0220))'),
        )
        params = (
            ('st', 'NOTICE_DATE,SECURITY_CODE'),
            ('sr', '-1,-1'),
            ('ps', '500'),
            ('p', f'{page}'),
            ('type', 'RPT_LICO_FN_CPD'),
            ('sty', 'ALL'),
            ('token', '894050c76af8597a853f5b408b759f5d'),
            #! 只选沪深A股
            ('filter',
             f'(SECURITY_TYPE_CODE in ("058001001","058001008")){date}'),

        )
        url = 'http://datacenter-web.eastmoney.com/api/data/get'
        response = session.get(url,
                               headers=EASTMONEY_REQUEST_HEADERS,
                               params=params)
        items = jsonpath(response.json(), '$..data[:]')
        if not items:
            break
        df = pd.DataFrame(items)
        dfs.append(df)
        page += 1
    if len(dfs) == 0:
        df = pd.DataFrame(columns=fields.values())
        return df
    df = pd.concat(dfs, axis=0, ignore_index=True)
    df = df.rename(columns=fields)[fields.values()]
    return df


@to_numeric
def get_latest_holder_number() -> pd.DataFrame:
    """
    获取沪深A股市场最新公开的股东数目变化情况

    Returns
    -------
    DataFrame
        沪深A股市场最新公开的股东数目变化情况

    Examples
    --------
    >>> import efinance as ef
    >>> ef.stock.get_latest_holder_number()
        股票代码  股票名称    股东人数     股东人数增减  较上期变化百分比            股东户数统计截止日        户均持股市值        户均持股数量           总市值          总股本                 公告日期
    0    688981  中芯国际  347706  -3.459784  -12461.0  2021-06-30 00:00:00  3.446469e+05   5575.005896  1.198358e+11   1938463000  2021-08-28 00:00:00
    1    688819  天能股份   36749 -11.319981   -4691.0  2021-06-30 00:00:00  1.176868e+06  26452.420474  4.324873e+10    972100000  2021-08-28 00:00:00
    2    688575   亚辉龙    7347 -74.389989  -21341.0  2021-06-30 00:00:00  2.447530e+06  55124.540629  1.798200e+10    405000000  2021-08-28 00:00:00
    3    688538  和辉光电  383993 -70.245095 -906527.0  2021-06-30 00:00:00  1.370180e+05  35962.732719  5.261396e+10  13809437625  2021-08-28 00:00:00
    4    688425  铁建重工  311356 -64.684452 -570284.0  2021-06-30 00:00:00  1.010458e+05  16510.746541  3.146121e+10   5140720000  2021-08-28 00:00:00
    ..      ...   ...     ...        ...       ...                  ...           ...           ...           ...          ...                  ...
    400  600618  氯碱化工   45372  -0.756814    -346.0  2014-06-30 00:00:00  1.227918e+05  16526.491581  5.571311e+09    749839976  2014-08-22 00:00:00
    401  601880  辽港股份   89923  -3.589540   -3348.0  2014-03-31 00:00:00  9.051553e+04  37403.111551  8.139428e+09   3363400000  2014-04-30 00:00:00
    402  600685  中船防务   52296  -4.807325   -2641.0  2014-03-11 00:00:00  1.315491e+05   8384.263691  6.879492e+09    438463454  2014-03-18 00:00:00
    403  000017  深中华A   21358 -10.800200   -2586.0  2013-06-30 00:00:00  5.943993e+04  14186.140556  1.269518e+09    302987590  2013-08-24 00:00:00
    404  601992  金隅集团   66736 -12.690355   -9700.0  2013-06-30 00:00:00  2.333339e+05  46666.785918  1.557177e+10   3114354625  2013-08-22 00:00:00

    """
    dfs: List[pd.DataFrame] = []
    page = 1
    fields = {
        'SECURITY_CODE': '股票代码',
        'SECURITY_NAME_ABBR': '股票名称',
        'HOLDER_NUM': '股东人数',
        'HOLDER_NUM_RATIO': '股东人数增减',
        'HOLDER_NUM_CHANGE': '较上期变化百分比',
        'END_DATE': '股东户数统计截止日',
        'AVG_MARKET_CAP': '户均持股市值',
        'AVG_HOLD_NUM': '户均持股数量',
        'TOTAL_MARKET_CAP': '总市值',
        'TOTAL_A_SHARES': '总股本',
        'HOLD_NOTICE_DATE': '公告日期'
    }

    while 1:
        params = (
            ('sortColumns', 'HOLD_NOTICE_DATE,SECURITY_CODE'),
            ('sortTypes', '-1,-1'),
            ('pageSize', '500'),
            ('pageNumber', page),
            ('reportName', 'RPT_HOLDERNUMLATEST'),
            ('columns', 'SECURITY_CODE,SECURITY_NAME_ABBR,END_DATE,INTERVAL_CHRATE,AVG_MARKET_CAP,AVG_HOLD_NUM,TOTAL_MARKET_CAP,TOTAL_A_SHARES,HOLD_NOTICE_DATE,HOLDER_NUM,PRE_HOLDER_NUM,HOLDER_NUM_CHANGE,HOLDER_NUM_RATIO,END_DATE,PRE_END_DATE'),
            ('quoteColumns', 'f2,f3'),
            ('source', 'WEB'),
            ('client', 'WEB'),
            #! 只选沪深A股
            ('filter',
             f'(SECURITY_TYPE_CODE in ("058001001","058001008"))'),

        )
        response = session.get('http://datacenter-web.eastmoney.com/api/data/v1/get',
                               headers=EASTMONEY_REQUEST_HEADERS,
                               params=params)
        items = jsonpath(response.json(), '$..data[:]')
        if not items:
            break
        df = pd.DataFrame(items)
        df = df.rename(columns=fields)[fields.values()]
        page += 1
        dfs.append(df)
    if len(dfs) == 0:
        df = pd.DataFrame(columns=fields.values())
        return df
    df = pd.concat(dfs)
    return df


@to_numeric
@retry(tries=3)
def get_daily_billboard(start_date: str = None,
                        end_date: str = None) -> pd.DataFrame:
    """
    获取指定日期区间的龙虎榜详情数据

    Parameters
    ----------
    start_date : str, optional
        开始日期
        部分可选示例如下

        - ``None`` 最新一个榜单公开日(默认值)
        - ``"2021-08-27"`` 2021年8月27日

    end_date : str, optional
        结束日期
        部分可选示例如下
        
        - ``None`` 最新一个榜单公开日(默认值)
        - ``"2021-08-31"`` 2021年8月31日

    Returns
    -------
    DataFrame
        龙虎榜详情数据

    Examples
    --------
    >>> import efinance as ef
    >>> # 获取最新一个公开的龙虎榜数据(后面还有获取指定日期区间的示例代码)
    >>> ef.stock.get_daily_billboard()
        股票代码  股票名称        上榜日期                解读     收盘价      涨跌幅      换手率        龙虎榜净买额        龙虎榜买入额        龙虎榜卖出额        龙虎榜成交额      市场总成交额  净买额占总成交比   成交额占总成交比          流通市值                                  上榜原因
    0   000608  阳光股份  2021-08-27    卖一主卖，成功率48.36%    3.73  -9.9034   3.8430 -8.709942e+06  1.422786e+07  2.293780e+07  3.716565e+07   110838793 -7.858208  33.531268  2.796761e+09                      日跌幅偏离值达到7%的前5只证券
    1   000751  锌业股份  2021-08-27    主力做T，成功率18.84%    5.32  -2.9197  19.6505 -1.079219e+08  5.638899e+07  1.643109e+08  2.206999e+08  1462953973 -7.376984  15.085906  7.500502e+09                       日振幅值达到15%的前5只证券
    2   000762  西藏矿业  2021-08-27  北京资金买入，成功率39.42%   63.99   1.0741  15.6463  2.938758e+07  4.675541e+08  4.381665e+08  9.057206e+08  4959962598  0.592496  18.260633  3.332571e+10                       日振幅值达到15%的前5只证券
    3   000833  粤桂股份  2021-08-27  实力游资买入，成功率44.55%    8.87  10.0496   8.8263  4.993555e+07  1.292967e+08  7.936120e+07  2.086580e+08   895910429  5.573721  23.290046  3.353614e+09              连续三个交易日内，涨幅偏离值累计达到20%的证券
    4   001208  华菱线缆  2021-08-27  1家机构买入，成功率40.43%   19.72   4.3386  46.1985  4.055258e+07  1.537821e+08  1.132295e+08  2.670117e+08  1203913048  3.368398  22.178651  2.634710e+09                       日换手率达到20%的前5只证券
    ..     ...   ...         ...               ...     ...      ...      ...           ...           ...           ...           ...         ...       ...        ...           ...                                   ...
    70  688558  国盛智科  2021-08-27    买一主买，成功率38.71%   60.72   1.6064  34.0104  1.835494e+07  1.057779e+08  8.742293e+07  1.932008e+08   802569300  2.287023  24.072789  2.321743e+09              有价格涨跌幅限制的日换手率达到30%的前五只证券
    71  688596  正帆科技  2021-08-27  1家机构买入，成功率57.67%   26.72   3.1660   3.9065 -1.371039e+07  8.409046e+07  9.780085e+07  1.818913e+08   745137400 -1.839982  24.410438  4.630550e+09  有价格涨跌幅限制的连续3个交易日内收盘价格涨幅偏离值累计达到30%的证券
    72  688663   新风光  2021-08-27    卖一主卖，成功率37.18%   28.17 -17.6316  32.2409  1.036460e+07  5.416901e+07  4.380440e+07  9.797341e+07   274732700  3.772613  35.661358  8.492507e+08           有价格涨跌幅限制的日收盘价格跌幅达到15%的前五只证券
    73  688663   新风光  2021-08-27    卖一主卖，成功率37.18%   28.17 -17.6316  32.2409  1.036460e+07  5.416901e+07  4.380440e+07  9.797341e+07   274732700  3.772613  35.661358  8.492507e+08              有价格涨跌幅限制的日换手率达到30%的前五只证券
    74  688667  菱电电控  2021-08-27  1家机构卖出，成功率49.69%  123.37 -18.8996  17.7701 -2.079877e+06  4.611216e+07  4.819204e+07  9.430420e+07   268503400 -0.774618  35.122163  1.461225e+09           有价格涨跌幅限制的日收盘价格跌幅达到15%的前五只证券


    >>> # 获取指定日期区间的龙虎榜数据
    >>> start_date = '2021-08-20' # 开始日期
    >>> end_date = '2021-08-27' # 结束日期
    >>> ef.stock.get_daily_billboard(start_date = start_date,end_date = end_date)
        股票代码  股票名称        上榜日期                解读     收盘价      涨跌幅      换手率        龙虎榜净买额        龙虎榜买入额        龙虎榜卖出额        龙虎榜成交额      市场总成交额   净买额占总成交比    成交额占总成交比          流通市值                           上榜原因
    0    000608  阳光股份  2021-08-27    卖一主卖，成功率48.36%    3.73  -9.9034   3.8430 -8.709942e+06  1.422786e+07  2.293780e+07  3.716565e+07   110838793  -7.858208   33.531268  2.796761e+09               日跌幅偏离值达到7%的前5只证券
    1    000751  锌业股份  2021-08-27    主力做T，成功率18.84%    5.32  -2.9197  19.6505 -1.079219e+08  5.638899e+07  1.643109e+08  2.206999e+08  1462953973  -7.376984   15.085906  7.500502e+09                日振幅值达到15%的前5只证券
    2    000762  西藏矿业  2021-08-27  北京资金买入，成功率39.42%   63.99   1.0741  15.6463  2.938758e+07  4.675541e+08  4.381665e+08  9.057206e+08  4959962598   0.592496   18.260633  3.332571e+10                日振幅值达到15%的前5只证券
    3    000833  粤桂股份  2021-08-27  实力游资买入，成功率44.55%    8.87  10.0496   8.8263  4.993555e+07  1.292967e+08  7.936120e+07  2.086580e+08   895910429   5.573721   23.290046  3.353614e+09       连续三个交易日内，涨幅偏离值累计达到20%的证券
    4    001208  华菱线缆  2021-08-27  1家机构买入，成功率40.43%   19.72   4.3386  46.1985  4.055258e+07  1.537821e+08  1.132295e+08  2.670117e+08  1203913048   3.368398   22.178651  2.634710e+09                日换手率达到20%的前5只证券
    ..      ...   ...         ...               ...     ...      ...      ...           ...           ...           ...           ...         ...        ...         ...           ...                            ...
    414  605580  恒盛能源  2021-08-20    买一主买，成功率33.33%   13.28  10.0249   0.4086  2.413149e+06  2.713051e+06  2.999022e+05  3.012953e+06     2713051  88.945937  111.054054  6.640000e+08  有价格涨跌幅限制的日收盘价格涨幅偏离值达到7%的前三只证券
    415  688029  南微医学  2021-08-20  4家机构卖出，成功率55.82%  204.61 -18.5340   8.1809 -1.412053e+08  1.883342e+08  3.295394e+08  5.178736e+08   762045800 -18.529760   67.958326  9.001510e+09    有价格涨跌幅限制的日收盘价格跌幅达到15%的前五只证券
    416  688408   中信博  2021-08-20  4家机构卖出，成功率47.86%  179.98  -0.0666  15.3723 -4.336304e+07  3.750919e+08  4.184550e+08  7.935469e+08   846547400  -5.122340   93.739221  5.695886e+09      有价格涨跌幅限制的日价格振幅达到30%的前五只证券
    417  688556  高测股份  2021-08-20  上海资金买入，成功率60.21%   51.97  17.0495  10.6452 -3.940045e+07  1.642095e+08  2.036099e+08  3.678194e+08   575411600  -6.847351   63.922831  5.739089e+09    有价格涨跌幅限制的日收盘价格涨幅达到15%的前五只证券
    418  688636   智明达  2021-08-20  2家机构买入，成功率47.37%  161.90  15.8332  11.9578  2.922406e+07  6.598126e+07  3.675721e+07  1.027385e+08   188330100  15.517464   54.552336  1.647410e+09    有价格涨跌幅限制的日收盘价格涨幅达到15%的前五只证券


    """
    today = datetime.today().date()
    mode = 'auto'
    if start_date is None:
        start_date = today

    if end_date is None:
        end_date = today

    if isinstance(start_date, str):
        mode = 'user'
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if isinstance(end_date, str):
        mode = 'user'
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    fields = EASTMONEY_STOCK_DAILY_BILL_BOARD_FIELDS
    bar: tqdm = None

    while 1:

        dfs: List[pd.DataFrame] = []
        page = 1
        while 1:
            params = (
                ('sortColumns', 'TRADE_DATE,SECURITY_CODE'),
                ('sortTypes', '-1,1'),
                ('pageSize', '500'),
                ('pageNumber', page),
                ('reportName', 'RPT_DAILYBILLBOARD_DETAILS'),
                ('columns', 'ALL'),
                ('source', 'WEB'),
                ('client', 'WEB'),
                ('filter',
                 f"(TRADE_DATE<='{end_date}')(TRADE_DATE>='{start_date}')"),
            )

            url = 'http://datacenter-web.eastmoney.com/api/data/v1/get'

            response = session.get(url,params=params)
            if bar is None:
                pages = jsonpath(response.json(), '$..pages')

                if pages and pages[0] != 1:
                    total = pages[0]
                    bar = tqdm(total=int(total))
            if bar is not None:
                bar.update()

            items = jsonpath(response.json(), '$..data[:]')
            if not items:
                break
            page += 1
            df = pd.DataFrame(items).rename(columns=fields)[fields.values()]
            dfs.append(df)
        if mode == 'user':
            break
        if len(dfs) == 0:
            start_date = start_date-timedelta(1)
            end_date = end_date-timedelta(1)

        if len(dfs) > 0:
            break
    if len(dfs) == 0:
        df = pd.DataFrame(columns=fields.values())
        return df

    df = pd.concat(dfs, ignore_index=True)
    df['上榜日期'] = df['上榜日期'].astype('str').apply(lambda x: x.split(' ')[0])
    return df
