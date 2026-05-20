import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz
import ta

# Fetch stock data based on ticker, period, & interval through Yahoo Finance API
def fetch_stock_data(ticker, period, interval):
    try:
        data = yf.download(ticker, period=period, interval=interval)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if data.empty:
            st.error(f"No data found for {ticker}. Please check the ticker symbol and try again.")
            return None
        return data
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return None

# Cache real-time sidebar data to avoid hammering the Yahoo Finance API on every rerender
@st.cache_data(ttl=60)
def fetch_realtime_data(symbol):
    return fetch_stock_data(symbol, '1d', '1m')

# Format the date & time to ensure it is timezone aware with correct formatting
def process_data(data):
    if data.index.tzinfo is None:
        data.index = data.index.tz_localize('UTC')
    data.index = data.index.tz_convert('US/Eastern')
    data.reset_index(inplace=True)
    if 'Date' in data.columns:
        data.rename(columns={'Date': 'Datetime'}, inplace=True)
    return data

# Calculate basic metrics from stock data
def calculate_metrics(data):
    close_series = ensure_series(data, 'Close')
    high_series = ensure_series(data, 'High')
    low_series = ensure_series(data, 'Low')
    volume_series = ensure_series(data, 'Volume')

    last_close = float(close_series.iloc[-1])
    prev_close = float(close_series.iloc[0])
    change = last_close - prev_close
    pct_change = (change / prev_close) * 100
    high = float(high_series.max())
    low = float(low_series.min())
    volume = int(volume_series.sum())
    return last_close, change, pct_change, high, low, volume

def to_numeric_series(values):
    if isinstance(values, pd.DataFrame):
        values = values.iloc[:, 0]
    return pd.to_numeric(values, errors='coerce')

def ensure_series(data, col):
    if col not in data.columns:
        return pd.Series(dtype='float64')
    values = data[col]
    if isinstance(values, pd.DataFrame):
        values = values.iloc[:, 0]
    return values

def convert_column_to_numeric(data, col):
    return to_numeric_series(ensure_series(data, col))

# Add technical indicators (SMA, EMA, RSI)
def add_technical_indicators(data):
    close = convert_column_to_numeric(data, 'Close')
    data['SMA_20'] = ta.trend.sma_indicator(close, window=20)
    data['EMA_20'] = ta.trend.ema_indicator(close, window=20)
    data['RSI_14'] = ta.momentum.rsi(close, window=14)
    return data

# Dashboard app page layout
st.set_page_config(layout='wide')
st.title('Real-Time Stock Dashboard')

# Sidebar for user input parameters
st.sidebar.header('Chart Parameters')
ticker = st.sidebar.text_input('Ticker', 'AAPL')
time_period = st.sidebar.selectbox('Time Period', ['1d', '5d', '1mo', '3mo', '6mo', '1y', '5y', 'max'])
chart_type = st.sidebar.selectbox('Chart Type', ['Candlestick', 'Line'])
indicators = st.sidebar.multiselect('Technical Indicators', ['SMA 20', 'EMA 20', 'RSI 14'])
currency = st.sidebar.selectbox('Currency', ['INR', 'USD'])

st.sidebar.header('Portfolio Tracker')
portfolio_symbol = st.sidebar.text_input('Add Symbol', '')
portfolio_shares = st.sidebar.number_input('Shares', min_value=0.0, value=0.0, step=0.1, format='%.2f')
portfolio_cost = st.sidebar.number_input('Cost Basis per Share', min_value=0.0, value=0.0, step=0.01, format='%.2f')
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = []

if st.sidebar.button('Add to Portfolio'):
    if portfolio_symbol and portfolio_shares > 0:
        st.session_state.portfolio.append({
            'symbol': portfolio_symbol.strip().upper(),
            'shares': float(portfolio_shares),
            'cost_basis': float(portfolio_cost)
        })
        st.experimental_rerun()

if st.sidebar.button('Clear Portfolio'):
    st.session_state.portfolio = []
    st.experimental_rerun()

# Interval Mapping
interval_mapping = {
    '1d': '1m',
    '5d': '5m',
    '1mo': '1h',
    '3mo': '1d',
    '6mo': '1d',
    '1y': '1wk',
    '5y': '1mo',
    'max': '1mo',
}

def get_fx_rate(base='USD', quote='INR'):
    if base == quote:
        return 1.0
    symbol = f"{base}{quote}=X"
    try:
        fx_data = yf.download(symbol, period='1d', interval='1d')
        if isinstance(fx_data.columns, pd.MultiIndex):
            fx_data.columns = fx_data.columns.get_level_values(0)
        if fx_data.empty:
            return 1.0
        return float(fx_data['Close'].iloc[-1])
    except Exception:
        return 1.0

def get_current_price(symbol, currency='INR'):
    data = yf.download(symbol, period='1d', interval='1m')
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if data.empty:
        return None
    close_price = convert_column_to_numeric(data, 'Close')
    if close_price.empty:
        return None
    fx_rate = get_fx_rate('USD', currency)
    return float(close_price.iloc[-1]) * fx_rate

# Update dashboard based on user inputs
if st.sidebar.button('Update'):
    data = fetch_stock_data(ticker, time_period, interval_mapping[time_period])
    if data is not None:
        data = process_data(data)
        fx_rate = get_fx_rate('USD', currency)
        for col in ['Open', 'High', 'Low', 'Close']:
            if col in data.columns:
                data[col] = convert_column_to_numeric(data, col) * fx_rate
        data = add_technical_indicators(data)

        last_close, change, pct_change, high, low, volume = calculate_metrics(data)

        # Display metrics
        st.metric(label=f"{ticker} Last Price", value=f"{last_close:.2f} {currency}", delta=f"{change:.2f} ({pct_change:.2f}%)")
        col1, col2, col3 = st.columns(3)
        col1.metric('High', f"{high:.2f} {currency}")
        col2.metric('Low', f"{low:.2f} {currency}")
        col3.metric('Volume', f"{volume:,}")

        # Plot the Stock Price Chart
        fig = go.Figure()
        if chart_type == 'Candlestick':
            fig.add_trace(go.Candlestick(x=data['Datetime'],
                                         open=data['Open'],
                                         high=data['High'],
                                         low=data['Low'],
                                         close=data['Close']))
        else:
            fig = px.line(data, x='Datetime', y='Close')

        # Add selected technical indicators to chart
        for indicator in indicators:
            if indicator == 'SMA 20':
                fig.add_trace(go.Scatter(x=data['Datetime'], y=data['SMA_20'], name='SMA 20'))
            elif indicator == 'EMA 20':
                fig.add_trace(go.Scatter(x=data['Datetime'], y=data['EMA_20'], name='EMA 20'))
            elif indicator == 'RSI 14':
                fig.add_trace(go.Scatter(x=data['Datetime'], y=data['RSI_14'], name='RSI 14', yaxis="y2"))

        # Formatting of the chart
        fig.update_layout(title=f"{ticker} {time_period.upper()} Chart",
                          xaxis_title='Time',
                          yaxis_title=f'Price ({currency})',
                          yaxis2=dict(title='RSI', overlaying='y', side='right', showgrid=False),
                          height=600)
        st.plotly_chart(fig, use_container_width=True)

        # Display historical data & technical indicators
        st.subheader('Historical Data')
        st.dataframe(data[['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']])

        st.subheader('Technical Indicators')
        st.dataframe(data[['Datetime', 'SMA_20', 'EMA_20', 'RSI_14']])

# Portfolio tracker output
st.subheader('Portfolio Tracker')
portfolio_data = st.session_state.get('portfolio', [])
if portfolio_data:
    portfolio_rows = []
    total_value = 0.0
    total_cost = 0.0
    for position in portfolio_data:
        symbol = position['symbol']
        shares = position['shares']
        cost_basis = position['cost_basis']
        current_price = get_current_price(symbol, currency)
        market_value = None
        profit_loss = None
        if current_price is not None:
            market_value = shares * current_price
            cost_value = shares * cost_basis
            profit_loss = market_value - cost_value
            total_value += market_value
            total_cost += cost_value
        portfolio_rows.append({
            'Symbol': symbol,
            'Shares': shares,
            f'Current Price ({currency})': current_price if current_price is not None else 'N/A',
            f'Market Value ({currency})': market_value if market_value is not None else 'N/A',
            f'Cost Basis ({currency})': cost_basis,
            f'Unrealized P/L ({currency})': profit_loss if profit_loss is not None else 'N/A'
        })
    st.dataframe(pd.DataFrame(portfolio_rows))
    if total_cost > 0:
        total_pl = total_value - total_cost
        st.metric(label='Portfolio Value', value=f"{total_value:,.2f} {currency}", delta=f"{total_pl:,.2f} {currency}")
else:
    st.info('Add positions to your portfolio using the sidebar inputs.')

# Real-time stock prices of selected symbols in sidebar
st.sidebar.header('Real-Time Stock Prices')
stock_symbols = ['AAPL', 'GOOGL', 'AMZN', 'MSFT']
for symbol in stock_symbols:
    real_time_data = fetch_realtime_data(symbol)
    if real_time_data is not None:
        real_time_data = process_data(real_time_data)
        fx_rate = get_fx_rate('USD', currency)
        real_time_data['Close'] = convert_column_to_numeric(real_time_data, 'Close') * fx_rate
        real_time_data['Open'] = convert_column_to_numeric(real_time_data, 'Open') * fx_rate
        last_price = float(ensure_series(real_time_data, 'Close').iloc[-1])
        change = last_price - float(ensure_series(real_time_data, 'Open').iloc[0])
        pct_change = (change / float(ensure_series(real_time_data, 'Open').iloc[0])) * 100
        st.sidebar.metric(f"{symbol}", f"{last_price:.2f} {currency}", f"{change:.2f} ({pct_change:.2f}%)")

# Sidebar information section
st.sidebar.subheader('About')
st.sidebar.info('This dashboard provides real-time stock data and technical indicators for various time periods.')
