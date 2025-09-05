import streamlit as st
import yfinance as yf
from pykrx import stock
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import json
import subprocess
import signal
import time
import warnings
import gspread
from google.oauth2.service_account import Credentials
warnings.filterwarnings('ignore')

# 페이지 설정
st.set_page_config(
    page_title="주식 하락률 모니터링",
    page_icon="🍣",
    layout="wide"
)

# 세션 상태 초기화
if 'monitoring_stocks' not in st.session_state:
    st.session_state.monitoring_stocks = {}
if 'monitoring_active' not in st.session_state:
    st.session_state.monitoring_active = False
if 'stocks_loaded' not in st.session_state:
    st.session_state.stocks_loaded = False

# Google Sheets 설정
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SERVICE_ACCOUNT_FILE = 'gen-lang-client-0213805963-b103cc47143a.json'
SPREADSHEET_NAME = 'stock-monitoring'

def get_google_sheets_client():
    """Google Sheets 클라이언트 생성"""
    try:
        # Streamlit Secrets에서 서비스 계정 정보 가져오기
        service_account_info = st.secrets["GOOGLE_SERVICE_ACCOUNT"]
        creds = Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES
        )
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Google Sheets 연결 실패: {e}")
        return None

def save_stocks_to_sheets():
    """모니터링 종목을 Google Sheets에 저장"""
    try:
        client = get_google_sheets_client()
        if not client:
            return False
        
        # 스프레드시트 열기 (없으면 생성)
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            # 스프레드시트 생성 시도
            try:
                spreadsheet = client.create(SPREADSHEET_NAME)
                st.success("✅ 새 Google Sheets 문서가 생성되었습니다!")
            except Exception as e:
                st.error(f"스프레드시트 생성 실패: {e}")
                st.info("수동으로 'stock-monitoring' 스프레드시트를 생성하고 서비스 계정과 공유해주세요.")
                st.info("서비스 계정 이메일: sheets-writer@gen-lang-client-0213805963.iam.gserviceaccount.com")
                return False
        
        # 첫 번째 시트 선택
        worksheet = spreadsheet.sheet1
        
        # 헤더 설정 - 기준 날짜와 종가 추가
        headers = ['종목코드', '종목명', '타입', '기준날짜', '기준종가']
        worksheet.clear()
        worksheet.append_row(headers)
        
        # 데이터 추가
        for symbol, info in st.session_state.monitoring_stocks.items():
            # 기준 날짜와 종가 정보 추출
            base_date = info['stats'].get('base_date', '')
            base_close = info['stats'].get('base_close', info['stats']['last_close'])
            
            row = [symbol, info['name'], info['type'], base_date, str(base_close)]
            worksheet.append_row(row)
        
        st.success("✅ Google Sheets에 저장 완료!")
        return True
        
    except Exception as e:
        st.error(f"Google Sheets 저장 실패: {e}")
        return False

def load_stocks_from_sheets():
    """Google Sheets에서 모니터링 종목 불러오기"""
    try:
        client = get_google_sheets_client()
        if not client:
            return False
        
        # 스프레드시트 열기
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            worksheet = spreadsheet.sheet1
            
            # 모든 값 가져오기
            worksheet = spreadsheet.get_worksheet(0)
            all_values = worksheet.get_all_values()
            
            if len(all_values) <= 1:  # 헤더만 있거나 빈 경우
                st.info("Google Sheets에 저장된 데이터가 없습니다.")
                return True
            
            # 헤더 제외하고 데이터 처리
            stocks = {}
            for row in all_values[1:]:  # 헤더 제외
                if len(row) >= 3:
                    symbol = row[0]
                    name = row[1]
                    stock_type = row[2]
                    # 기준 날짜와 종가 정보 (있으면)
                    base_date = row[3] if len(row) > 3 else None
                    base_close = float(row[4]) if len(row) > 4 and row[4] else None
                    
                    stocks[symbol] = {
                        'name': name,
                        'type': stock_type,
                        'saved_base_date': base_date,
                        'saved_base_close': base_close
                    }
            
            if stocks:
                # 분석기로 현재 가격 정보 추가
                analyzer = StockAnalyzer()
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, (symbol, info) in enumerate(stocks.items()):
                    status_text.text(f"Google Sheets에서 불러오는 중: {info['name']} ({symbol})")
                    progress_bar.progress((idx + 1) / len(stocks))
                    
                    try:
                        df = analyzer.get_stock_data(symbol, info['type'])
                        if df is not None:
                            stats = analyzer.calculate_sigma_levels(df)
                            # 정확한 전일 종가 가져오기
                            base_close, base_date = analyzer.get_accurate_last_close(symbol, info['type'])
                            if base_close:
                                stats['base_close'] = base_close
                                stats['base_date'] = base_date.strftime('%Y-%m-%d') if base_date else ''
                            info['stats'] = stats
                            info['df'] = df
                    except Exception as e:
                        st.warning(f"{symbol} 데이터 로드 실패: {e}")
                
                progress_bar.empty()
                status_text.empty()
                
                # 세션 상태 업데이트
                st.session_state.monitoring_stocks.clear()
                st.session_state.monitoring_stocks.update(stocks)
                st.session_state.stocks_loaded = True
                
                # 캐시 무효화
                st.cache_data.clear()
                
                st.success(f"✅ Google Sheets에서 {len(stocks)}개 종목을 불러왔습니다!")
                return True
            else:
                st.info("Google Sheets에 저장된 종목이 없습니다.")
                return True
                
        except gspread.SpreadsheetNotFound:
            st.info("Google Sheets 문서를 찾을 수 없습니다. 새로 생성됩니다.")
            return False
            
    except Exception as e:
        st.error(f"Google Sheets에서 데이터를 불러올 수 없습니다: {e}")
        return False
    
class StockAnalyzer:
    def __init__(self):
        pass
    
    def get_accurate_last_close(self, symbol, stock_type='KR'):
        """정확한 전일 종가와 날짜 가져오기"""
        try:
            today = datetime.now()
            
            if stock_type == 'KR':
                # 한국 주식 - 전일 종가 명시적으로 가져오기
                # 주말과 공휴일을 고려하여 최근 거래일 찾기
                for i in range(1, 10):  # 최대 10일 전까지 확인
                    check_date = today - timedelta(days=i)
                    df = stock.get_market_ohlcv_by_date(
                        fromdate=check_date.strftime('%Y%m%d'),
                        todate=check_date.strftime('%Y%m%d'),
                        ticker=symbol
                    )
                    if not df.empty:
                        return df['종가'].iloc[-1], check_date
            else:
                # 미국 주식 - yfinance의 previous close 사용
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                if 'regularMarketPreviousClose' in info and info['regularMarketPreviousClose']:
                    # history에서 날짜 확인
                    hist = ticker.history(period='5d')
                    if not hist.empty and len(hist) > 1:
                        # 마지막에서 두 번째 날짜가 전일
                        prev_date = hist.index[-2].date() if len(hist) > 1 else hist.index[-1].date()
                        return info['regularMarketPreviousClose'], prev_date
                
                # info에서 못 구하면 history 사용
                hist = ticker.history(period='1mo')
                if not hist.empty:
                    # 오늘 데이터 제외하고 마지막 거래일
                    today_str = today.strftime('%Y-%m-%d')
                    hist_filtered = hist[hist.index.strftime('%Y-%m-%d') < today_str]
                    if not hist_filtered.empty:
                        last_close = hist_filtered['Close'].iloc[-1]
                        last_date = hist_filtered.index[-1].date()
                        return last_close, last_date
                        
        except Exception as e:
            st.warning(f"전일 종가 가져오기 실패 ({symbol}): {e}")
        
        return None, None
    
    def search_korean_stock(self, query):
        """한국 주식 검색"""
        try:
            # 6자리 숫자면 종목코드로 검색
            if query.isdigit() and len(query) == 6:
                name = stock.get_market_ticker_name(query)
                if name:
                    return query, name
            
            # 종목명으로 검색
            tickers = stock.get_market_ticker_list()
            query_upper = query.upper()
            
            # 전체 검색
            for ticker in tickers:
                try:
                    name = stock.get_market_ticker_name(ticker)
                    if name and query_upper in name.upper():
                        return ticker, name
                except Exception:
                    continue
            
            return None, None
        except Exception as e:
            return None, None
    
    def get_stock_data(self, symbol, stock_type='KR'):
        """주식 데이터 가져오기"""
        try:
            if stock_type == 'KR':
                # 한국 주식 - 오늘 데이터는 제외하고 가져오기
                today = datetime.now()
                yesterday = today - timedelta(days=1)
                
                df = stock.get_market_ohlcv_by_date(
                    fromdate=(today - timedelta(days=365*5)).strftime('%Y%m%d'),
                    todate=yesterday.strftime('%Y%m%d'),  # 어제까지만
                    ticker=symbol
                )
            
                if df is None or df.empty:
                    st.warning(f"종목코드 {symbol}에 대한 데이터가 없습니다.")
                    return None
                
                # 컬럼명 표준화
                if len(df.columns) == 6:
                    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume', 'Value']
                    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                elif len(df.columns) == 5:
                    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                
                if len(df) < 10:
                    st.warning(f"종목코드 {symbol}의 데이터가 부족합니다.")
                    return None
                
                df['Returns'] = df['Close'].pct_change() * 100
                
            else:
                # 미국 주식
                ticker = yf.Ticker(symbol)
                df = ticker.history(period='5y')
                
                # 오늘 데이터가 있으면 제외
                today = datetime.now().date()
                if not df.empty and df.index[-1].date() == today:
                    df = df[:-1]
                
                if df.empty:
                    return None
                
                df['Returns'] = df['Close'].pct_change() * 100
            
            return df.dropna()
            
        except Exception as e:
            st.error(f"데이터 가져오기 실패: {e}")
            return None
    
    def calculate_sigma_levels(self, df):
        """시그마 레벨 계산"""
        try:
            if df is None or df.empty:
                return None
            
            returns = df['Returns'].dropna()
            
            if len(returns) < 10:
                return None
            
            # 기본 통계
            mean = returns.mean()
            std = returns.std()
            
            # 시그마 레벨
            sigma_1 = mean - std
            sigma_2 = mean - 2 * std
            sigma_3 = mean - 3 * std
            
            # 마지막 종가 (데이터프레임의 마지막 값)
            last_close = df['Close'].iloc[-1]
            
            # 1년 데이터로 별도 계산
            if len(df) >= 252:
                returns_1y = df['Returns'].tail(252).dropna()
                if len(returns_1y) >= 10:
                    mean_1y = returns_1y.mean()
                    std_1y = returns_1y.std()
                    
                    sigma_1_1y = mean_1y - std_1y
                    sigma_2_1y = mean_1y - 2 * std_1y
                    sigma_3_1y = mean_1y - 3 * std_1y
                else:
                    sigma_1_1y, sigma_2_1y, sigma_3_1y = sigma_1, sigma_2, sigma_3
            else:
                sigma_1_1y, sigma_2_1y, sigma_3_1y = sigma_1, sigma_2, sigma_3
            
            return {
                'mean': mean,
                'std': std,
                '1sigma': sigma_1,
                '2sigma': sigma_2,
                '3sigma': sigma_3,
                '1sigma_1y': sigma_1_1y,
                '2sigma_1y': sigma_2_1y,
                '3sigma_1y': sigma_3_1y,
                'last_close': last_close,  # 데이터프레임의 마지막 종가
                'returns': returns.tolist()
            }
            
        except Exception as e:
            st.error(f"시그마 계산 실패: {e}")
            return None
    
    def get_current_price(self, symbol, stock_type='KR'):
        """현재가 가져오기"""
        try:
            if stock_type == 'KR':
                # 한국 주식 현재가
                today = datetime.now().strftime('%Y%m%d')
                price = stock.get_market_ohlcv_by_date(
                    fromdate=today,
                    todate=today,
                    ticker=symbol
                )
                if not price.empty:
                    return price['종가'].iloc[-1], price['전일대비'].iloc[-1]
            else:
                # 미국 주식 현재가
                ticker = yf.Ticker(symbol)
                info = ticker.info
                if 'regularMarketPrice' in info and info['regularMarketPrice']:
                    current = info['regularMarketPrice']
                    previous = info.get('regularMarketPreviousClose', current)
                    change = ((current - previous) / previous) * 100 if previous else 0
                    return current, change
            
            return None, None
            
        except Exception as e:
            return None, None

# Streamlit 앱 시작
st.subheader("🍣 주식 하락률 모니터링 시스템")
st.markdown("---")

# 탭 생성
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 0

tab1, tab2, tab3 = st.tabs(["📊 분석 결과", "📋 저장된 종목", "📈 백테스팅"])

# 사이드바
with st.sidebar:
    st.header("🦁 주식 시그마 분석")
    
    st.markdown("---")
    
    # 저장된 종목 불러오기
    st.header("🍚 저장된 종목")
    
    # Google Sheets에서 불러오기 버튼
    if st.button("📂 저장종목 불러오기", use_container_width=True, type="primary"):
        # 캐시 무효화를 위해 세션 상태 초기화
        st.session_state.stocks_loaded = False
        st.session_state.monitoring_stocks.clear()
        st.cache_data.clear()
        
        if load_stocks_from_sheets():
            st.rerun()
    
    if st.session_state.monitoring_stocks:
        if st.button("💾 Google Sheets 저장", use_container_width=True):
            save_stocks_to_sheets()
        st.markdown(f"**현재 종목 {len(st.session_state.monitoring_stocks)}개**")
    
    st.markdown("---")
    
    # 종목 추가 섹션
    st.header("➕ 종목 추가")
    
    # 검색 히스토리 초기화
    if 'search_history' not in st.session_state:
        st.session_state.search_history = []
    
    stock_input = st.text_input("종목명 또는 종목코드", placeholder="삼성전자 또는 005930", on_change=None)
    
    # 엔터키 또는 버튼 클릭으로 검색
    search_triggered = False
    
    if st.button("🔍 검색 및 분석", use_container_width=True):
        search_triggered = True
    
    # 엔터키 감지 (세션 상태로 관리)
    if 'last_input' not in st.session_state:
        st.session_state.last_input = ""
    
    if stock_input != st.session_state.last_input and stock_input.strip():
        st.session_state.last_input = stock_input
        search_triggered = True
    
    if search_triggered and stock_input:
        analyzer = StockAnalyzer()
        
        # 한 글자면 미국 주식으로 바로 처리
        if len(stock_input) == 1:
            symbol = stock_input.upper()
            name, stock_type = symbol, 'US'
            st.info(f"미국 주식: {symbol}")
        else:
            # 한국 주식 검색
            kr_code, kr_name = analyzer.search_korean_stock(stock_input)
            
            if kr_code:
                symbol, name, stock_type = kr_code, kr_name, 'KR'
                st.success(f"한국 주식: {name} ({kr_code})")
            else:
                symbol = stock_input.upper()
                name, stock_type = symbol, 'US'
                st.info(f"미국 주식: {symbol}")
        
        # 분석 결과를 세션에 저장
        with st.spinner('데이터 분석 중...'):
            df = analyzer.get_stock_data(symbol, stock_type)
            
            if df is not None:
                stats = analyzer.calculate_sigma_levels(df)
                
                # 정확한 전일 종가 가져오기
                base_close, base_date = analyzer.get_accurate_last_close(symbol, stock_type)
                
                if stats:
                    # 기준 종가와 날짜 추가
                    if base_close:
                        stats['base_close'] = base_close
                        stats['base_date'] = base_date.strftime('%Y-%m-%d') if base_date else ''
                    else:
                        stats['base_close'] = stats['last_close']
                        stats['base_date'] = df.index[-1].strftime('%Y-%m-%d')
                    
                    # 분석 결과를 세션에 저장
                    st.session_state.current_analysis = {
                        'symbol': symbol,
                        'name': name,
                        'type': stock_type,
                        'stats': stats,
                        'df': df
                    }
                    st.success(f"✅ {name} ({symbol}) 분석 완료! 탭 1에서 결과를 확인하세요.")
                    st.rerun()
                else:
                    st.error("분석에 실패했습니다.")
            else:
                st.error("주식 데이터를 가져올 수 없습니다.")

# 탭 1: 분석 결과
with tab1:
    # 분석기 초기화
    analyzer = StockAnalyzer()
    
    # 분석 결과 표시
    if 'current_analysis' in st.session_state:
        analysis = st.session_state.current_analysis
        
        # 분석 결과 제목과 추가 버튼을 한 줄에 배치
        col_title1, col_title2 = st.columns([3, 1])
        with col_title1:
            st.subheader(f"📊 {analysis['name']} ({analysis['symbol']}) 분석 결과")
        with col_title2:
            st.markdown("")  # 공간 확보
            if st.button(f"🎯 추가", use_container_width=True, type="primary", help=f"{analysis['name']}을 모니터링 목록에 추가"):
                st.session_state.monitoring_stocks[analysis['symbol']] = analysis
                st.success(f"{analysis['name']}이(가) 모니터링 목록에 추가되었습니다!")
                del st.session_state.current_analysis
                st.rerun()
        
        # 기준 종가 사용
        base_close = analysis['stats'].get('base_close', analysis['stats']['last_close'])
        base_date = analysis['stats'].get('base_date', '')
        
        # 주요 지표
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            current_price, price_change = analyzer.get_current_price(analysis['symbol'], analysis['type'])
            if current_price:
                if analysis['type'] == 'KR':
                    st.metric("현재가", f"₩{current_price:,.0f}", f"{price_change:+.2f}%")
                else:
                    st.metric("현재가", f"${current_price:,.2f}", f"{price_change:+.2f}%")
            else:
                if analysis['type'] == 'KR':
                    st.metric("기준 종가", f"₩{base_close:,.0f}")
                    if base_date:
                        st.caption(f"기준일: {base_date}")
                else:
                    st.metric("기준 종가", f"${base_close:,.2f}")
                    if base_date:
                        st.caption(f"기준일: {base_date}")
        with col_b:
            st.metric("평균 수익률", f"{analysis['stats']['mean']:.2f}%")
        with col_c:
            st.metric("표준편차", f"{analysis['stats']['std']:.2f}%")
        with col_d:
            # 현재 변화율과 시그마 레벨 비교
            if current_price:
                change_pct = ((current_price - base_close) / base_close) * 100
                if change_pct <= analysis['stats']['3sigma']:
                    level = "3σ 돌파!"
                    delta_color = "inverse"
                elif change_pct <= analysis['stats']['2sigma']:
                    level = "2σ 돌파!"
                    delta_color = "inverse"
                elif change_pct <= analysis['stats']['1sigma']:
                    level = "1σ 돌파!"
                    delta_color = "inverse"
                else:
                    level = "정상"
                    delta_color = "normal"
                st.metric("현재 상태", level, f"{change_pct:+.2f}%", delta_color=delta_color)
        
        # 시그마 하락시 가격 표시
        st.markdown("---")
        st.subheader(f"💰 시그마 하락시 목표 가격 (기준: {base_date if base_date else '마지막 거래일'})")
        
        # 1년 시그마 값들
        sigma_1_1y = analysis['stats'].get('1sigma_1y', analysis['stats']['1sigma'])
        sigma_2_1y = analysis['stats'].get('2sigma_1y', analysis['stats']['2sigma'])
        sigma_3_1y = analysis['stats'].get('3sigma_1y', analysis['stats']['3sigma'])
        
        # 시그마 하락시 가격 계산
        price_at_1sigma = base_close * (1 + sigma_1_1y / 100)
        price_at_2sigma = base_close * (1 + sigma_2_1y / 100)
        price_at_3sigma = base_close * (1 + sigma_3_1y / 100)
        
        # 통화 단위 설정
        if analysis['type'] == 'KR':
            currency = '₩'
            price_format = "{:,.0f}"
        else:
            currency = '$'
            price_format = "{:,.2f}"
        
        # 컬럼으로 표시
        price_col1, price_col2, price_col3 = st.columns(3)
        
        with price_col1:
            st.metric(
                f"1σ ({sigma_1_1y:.2f}%) 하락시",
                f"{currency}{price_format.format(price_at_1sigma)}"
            )
        
        with price_col2:
            st.metric(
                f"2σ ({sigma_2_1y:.2f}%) 하락시",
                f"{currency}{price_format.format(price_at_2sigma)}"
            )
        
        with price_col3:
            st.metric(
                f"3σ ({sigma_3_1y:.2f}%) 하락시",
                f"{currency}{price_format.format(price_at_3sigma)}"
            )
        
        # 기준 종가 정보
        st.caption(f"* 기준 종가: {currency}{price_format.format(base_close)} ({base_date if base_date else '마지막 거래일'})")
        
        # 시그마 레벨 상세 정보
        st.markdown("---")
        st.subheader("🎯 하락 알림 기준")
        
        # 5년과 1년 비교 탭
        tab_5y, tab_1y = st.tabs(["5년 기준", "1년 기준"])
        
        with tab_5y:
            # 5년 데이터로 실제 발생 확률 계산
            returns_5y = analysis['stats']['returns']
            sigma_1_5y = analysis['stats']['1sigma']
            sigma_2_5y = analysis['stats']['2sigma']
            sigma_3_5y = analysis['stats']['3sigma']
            
            actual_prob_1_5y = (np.array(returns_5y) <= sigma_1_5y).sum() / len(returns_5y) * 100
            actual_prob_2_5y = (np.array(returns_5y) <= sigma_2_5y).sum() / len(returns_5y) * 100
            actual_prob_3_5y = (np.array(returns_5y) <= sigma_3_5y).sum() / len(returns_5y) * 100
            
            sigma_df_5y = pd.DataFrame({
                '레벨': ['1시그마', '2시그마', '3시그마'],
                '하락률': [f"{sigma_1_5y:.2f}%", f"{sigma_2_5y:.2f}%", f"{sigma_3_5y:.2f}%"],
                '이론적 확률': ['15.87%', '2.28%', '0.13%'],
                '실제 발생률': [f"{actual_prob_1_5y:.2f}%", f"{actual_prob_2_5y:.2f}%", f"{actual_prob_3_5y:.2f}%"]
            })
            st.dataframe(sigma_df_5y, use_container_width=True, hide_index=True)
        
        with tab_1y:
            # 1년 데이터로 실제 발생 확률 계산
            if len(analysis['stats']['returns']) >= 252:
                returns_1y = analysis['stats']['returns'][-252:]
                
                actual_prob_1_1y = (np.array(returns_1y) <= sigma_1_1y).sum() / len(returns_1y) * 100
                actual_prob_2_1y = (np.array(returns_1y) <= sigma_2_1y).sum() / len(returns_1y) * 100
                actual_prob_3_1y = (np.array(returns_1y) <= sigma_3_1y).sum() / len(returns_1y) * 100
            else:
                actual_prob_1_1y, actual_prob_2_1y, actual_prob_3_1y = actual_prob_1_5y, actual_prob_2_5y, actual_prob_3_5y
            
            sigma_df_1y = pd.DataFrame({
                '레벨': ['1시그마', '2시그마', '3시그마'],
                '하락률': [f"{sigma_1_1y:.2f}%", f"{sigma_2_1y:.2f}%", f"{sigma_3_1y:.2f}%"],
                '이론적 확률': ['15.87%', '2.28%', '0.13%'],
                '실제 발생률': [f"{actual_prob_1_1y:.2f}%", f"{actual_prob_2_1y:.2f}%", f"{actual_prob_3_1y:.2f}%"]
            })
            st.dataframe(sigma_df_1y, use_container_width=True, hide_index=True)
        
        # 연도별 발생 횟수
        st.markdown("---")
        st.subheader("📅 연도별 시그마 하락 발생 횟수")
        
        # 연도별 통계 계산
        df_analysis = analysis['df'].copy()
        df_analysis['Returns'] = df_analysis['Close'].pct_change() * 100
        df_analysis['연도'] = df_analysis.index.year
        
        yearly_stats = {}
        for year in sorted(df_analysis['연도'].unique()):
            year_data = df_analysis[df_analysis['연도'] == year]
            returns_year = year_data['Returns'].dropna()
            
            yearly_stats[year] = {
                '1sigma': ((returns_year <= sigma_1_5y) & (returns_year > sigma_2_5y)).sum(),
                '2sigma': ((returns_year <= sigma_2_5y) & (returns_year > sigma_3_5y)).sum(),
                '3sigma': (returns_year <= sigma_3_5y).sum(),
                'total_days': len(returns_year)
            }
        
        yearly_data = []
        for year, data in yearly_stats.items():
            yearly_data.append({
                '연도': year,
                '거래일수': data['total_days'],
                '1σ 발생': data['1sigma'],
                '2σ 발생': data['2sigma'],
                '3σ 발생': data['3sigma']
            })
        yearly_df = pd.DataFrame(yearly_data)
        st.dataframe(yearly_df, use_container_width=True, hide_index=True)
    
        # 최근 발생일 및 연속 발생 정보
        st.markdown("---")
        st.subheader("📊 최근 시그마 하락 발생일")
        
        # 각 시그마 구간별 발생일 찾기
        df_analysis_clean = df_analysis.dropna()
        sigma_1_dates = df_analysis_clean[(df_analysis_clean['Returns'] <= sigma_1_5y) & 
                                        (df_analysis_clean['Returns'] > sigma_2_5y)].index
        sigma_2_dates = df_analysis_clean[(df_analysis_clean['Returns'] <= sigma_2_5y) & 
                                        (df_analysis_clean['Returns'] > sigma_3_5y)].index
        sigma_3_dates = df_analysis_clean[df_analysis_clean['Returns'] <= sigma_3_5y].index
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if len(sigma_1_dates) > 0:
                last_date = sigma_1_dates[-1]
                days_ago = (datetime.now().date() - last_date.date()).days
                st.metric("1σ 구간 최근 발생", f"{days_ago}일 전")
            else:
                st.metric("1σ 구간 최근 발생", "없음")
                
        with col2:
            if len(sigma_2_dates) > 0:
                last_date = sigma_2_dates[-1]
                days_ago = (datetime.now().date() - last_date.date()).days
                st.metric("2σ 구간 최근 발생", f"{days_ago}일 전")
            else:
                st.metric("2σ 구간 최근 발생", "없음")
                
        with col3:
            if len(sigma_3_dates) > 0:
                last_date = sigma_3_dates[-1]
                days_ago = (datetime.now().date() - last_date.date()).days
                st.metric("3σ 이하 최근 발생", f"{days_ago}일 전")
            else:
                st.metric("3σ 이하 최근 발생", "없음")
        
        # 상세 발생일 목록 (expander)
        with st.expander("📅 시그마 하락 발생일 상세"):
            tab1_detail, tab2_detail, tab3_detail = st.tabs(["2σ 구간 발생일", "3σ 이하 발생일", "극단적 하락 TOP 10"])
            
            with tab1_detail:
                if len(sigma_2_dates) > 0:
                    recent_2sigma = []
                    for date in sigma_2_dates[-20:]:  # 최근 20개
                        return_pct = df_analysis_clean.loc[date, 'Returns']
                        recent_2sigma.append({
                            '날짜': date.strftime('%Y-%m-%d'),
                            '수익률': f"{return_pct:.2f}%"
                        })
                    st.dataframe(pd.DataFrame(recent_2sigma), use_container_width=True, hide_index=True)
                    st.caption(f"2σ 구간: {sigma_3_5y:.2f}% < 하락률 ≤ {sigma_2_5y:.2f}%")
                else:
                    st.info("2σ 구간 하락 발생 이력이 없습니다.")
                    
            with tab2_detail:
                if len(sigma_3_dates) > 0:
                    recent_3sigma = []
                    for date in sigma_3_dates:  # 3σ는 모두 표시
                        return_pct = df_analysis_clean.loc[date, 'Returns']
                        recent_3sigma.append({
                            '날짜': date.strftime('%Y-%m-%d'),
                            '수익률': f"{return_pct:.2f}%"
                        })
                    st.dataframe(pd.DataFrame(recent_3sigma), use_container_width=True, hide_index=True)
                    st.caption(f"3σ 이하: 하락률 ≤ {sigma_3_5y:.2f}%")
                else:
                    st.info("3σ 이하 하락 발생 이력이 없습니다.")
                    
            with tab3_detail:
                # 최악의 하락일 TOP 10
                worst_days = df_analysis_clean.nsmallest(10, 'Returns')[['Returns']].copy()
                worst_days['날짜'] = worst_days.index.strftime('%Y-%m-%d')
                worst_days['수익률'] = worst_days['Returns'].apply(lambda x: f"{x:.2f}%")
                st.dataframe(worst_days[['날짜', '수익률']], use_container_width=True, hide_index=True)

        # 수익률 분포 차트
        st.markdown("---")
        st.subheader("📈 일일 수익률 분포 (5년)")
        
        fig = go.Figure()
        
        # 히스토그램
        fig.add_trace(go.Histogram(
            x=analysis['stats']['returns'],
            nbinsx=50,
            name='수익률 분포',
            marker_color='lightblue',
            opacity=0.7
        ))
        
        # 시그마 레벨 선
        colors = ['green', 'orange', 'red']
        for i, (level, value) in enumerate([
            ('1σ', analysis['stats']['1sigma']),
            ('2σ', analysis['stats']['2sigma']),
            ('3σ', analysis['stats']['3sigma'])
        ]):
            fig.add_vline(x=value, line_dash="dash", line_color=colors[i], 
                         annotation_text=f"{level}: {value:.1f}%")
        
        # 평균선
        fig.add_vline(x=analysis['stats']['mean'], line_dash="dash", 
                     line_color="blue", annotation_text=f"평균: {analysis['stats']['mean']:.1f}%")
        
        fig.update_layout(
            xaxis_title="일일 수익률 (%)",
            yaxis_title="빈도",
            showlegend=False,
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
# 탭 2: 저장된 종목
with tab2:
    st.subheader("📋 저장된 종목 목록")
    
    # 텔레그램 모니터링 안내
    st.info("""
    📱 **텔레그램 알림**
    1. 로컬 컴퓨터에서 stock_monitor.py 실행 시 저장된 종목들 자동으로 모니터링 시작
    2. 시그마 레벨 도달 시 텔레그램 알림
    """)

    # 새로고침 버튼
    if st.button("🔄 새로고침", use_container_width=True):
        # 모든 종목 데이터 업데이트
        analyzer = StockAnalyzer()
        for symbol, info in st.session_state.monitoring_stocks.items():
            try:
                # 정확한 전일 종가 가져오기
                base_close, base_date = analyzer.get_accurate_last_close(symbol, info['type'])
                if base_close:
                    info['stats']['base_close'] = base_close
                    info['stats']['base_date'] = base_date.strftime('%Y-%m-%d') if base_date else ''
            except Exception as e:
                st.warning(f"{symbol} 업데이트 실패: {e}")
        st.rerun()
        
    # 현재가 표시 - 새로운 표 형식
    if st.session_state.monitoring_stocks:
        # 한국/미국 종목 분리
        kr_stocks = {k: v for k, v in st.session_state.monitoring_stocks.items() if v['type'] == 'KR'}
        us_stocks = {k: v for k, v in st.session_state.monitoring_stocks.items() if v['type'] == 'US'}
        
        # 탭 생성
        tab_kr, tab_us = st.tabs([f"🇰🇷 한국 주식 ({len(kr_stocks)})", f"🇺🇸 미국 주식 ({len(us_stocks)})"])
        
        analyzer = StockAnalyzer()
        
        # 한국 주식 탭
        with tab_kr:
            if kr_stocks:
                current_prices_kr = []
                # 한국 주식은 이름순으로 정렬
                sorted_kr_stocks = sorted(kr_stocks.items(), key=lambda x: x[1]['name'])
                for symbol, info in sorted_kr_stocks:
                    try:
                        # 기준 종가 사용
                        base_close = info['stats'].get('base_close', info['stats']['last_close'])
                        base_date = info['stats'].get('base_date', '')
                        
                        # 1년 시그마 값들 (퍼센트)
                        sigma_1_1y = info['stats'].get('1sigma_1y', info['stats']['1sigma'])
                        sigma_2_1y = info['stats'].get('2sigma_1y', info['stats']['2sigma'])
                        sigma_3_1y = info['stats'].get('3sigma_1y', info['stats']['3sigma'])
                        
                        # 시그마 하락시 가격 계산
                        price_at_1sigma = base_close * (1 + sigma_1_1y / 100)
                        price_at_2sigma = base_close * (1 + sigma_2_1y / 100)
                        price_at_3sigma = base_close * (1 + sigma_3_1y / 100)
                        
                        current_prices_kr.append({
                            '종목': f"{info['name']} ({symbol})",
                            '기준 종가': f"₩{base_close:,.0f}",
                            '기준일': base_date if base_date else '-',
                            '1σ(1년)': f"{sigma_1_1y:.2f}%",
                            '1σ 하락시 가격': f"₩{price_at_1sigma:,.0f}",
                            '2σ(1년)': f"{sigma_2_1y:.2f}%",
                            '2σ 하락시 가격': f"₩{price_at_2sigma:,.0f}",
                            '3σ(1년)': f"{sigma_3_1y:.2f}%",
                            '3σ 하락시 가격': f"₩{price_at_3sigma:,.0f}"
                        })
                    except Exception as e:
                        st.error(f"{symbol} 오류: {str(e)}")
                
                if current_prices_kr:
                    df_current_kr = pd.DataFrame(current_prices_kr)
                    # 선택 가능한 DataFrame으로 표시
                    selected_kr = st.dataframe(
                        df_current_kr, 
                        use_container_width=True, 
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row"
                    )
                    
                    # 선택된 행이 있으면 분석 실행
                    if selected_kr and len(selected_kr.selection.rows) > 0:
                        selected_idx = selected_kr.selection.rows[0]
                        selected_stock = df_current_kr.iloc[selected_idx]
                        symbol = selected_stock['종목'].split('(')[-1].rstrip(')')
                        
                        # 선택된 종목 정보 표시
                        st.markdown(f"**선택된 종목: {selected_stock['종목']}**")
                        
                        # 버튼을 동일한 행에 배치
                        col_analyze, col_delete = st.columns(2)
                        
                        with col_analyze:
                            # 분석 결과 탭으로 이동 버튼
                            if st.button("📊 분석 결과 보기", key=f"analyze_kr_{symbol}", use_container_width=True):
                                # 선택된 종목의 데이터를 분석 결과에 설정
                                if symbol in st.session_state.monitoring_stocks:
                                    stock_info = st.session_state.monitoring_stocks[symbol]
                                    analyzer = StockAnalyzer()
                                    
                                    # 종목 데이터 가져오기
                                    df = analyzer.get_stock_data(symbol, stock_info['type'])
                                    if df is not None:
                                        # 분석 결과를 세션에 저장
                                        st.session_state.current_analysis = {
                                            'symbol': symbol,
                                            'name': stock_info['name'],
                                            'type': stock_info['type'],
                                            'df': df,
                                            'stats': stock_info['stats']
                                        }
                                        st.success(f"{selected_stock['종목']} 분석 데이터가 로드되었습니다!")
                                        st.rerun()
                        
                        with col_delete:
                            # 삭제 버튼
                            if st.button(f"🗑️ 삭제", key=f"delete_kr_{symbol}", use_container_width=True):
                                if symbol in st.session_state.monitoring_stocks:
                                    del st.session_state.monitoring_stocks[symbol]
                                    save_stocks_to_sheets()
                                    st.success(f"{selected_stock['종목']} 삭제 완료!")
                                    st.rerun()
            else:
                st.info("저장된 한국 주식이 없습니다.")
        
        # 미국 주식 탭
        with tab_us:
            if us_stocks:
                current_prices_us = []
                # 미국 주식은 심볼순으로 정렬
                sorted_us_stocks = sorted(us_stocks.items(), key=lambda x: x[0])
                for symbol, info in sorted_us_stocks:
                    try:
                        # 기준 종가 사용
                        base_close = info['stats'].get('base_close', info['stats']['last_close'])
                        base_date = info['stats'].get('base_date', '')
                        
                        # 1년 시그마 값들 (퍼센트)
                        sigma_1_1y = info['stats'].get('1sigma_1y', info['stats']['1sigma'])
                        sigma_2_1y = info['stats'].get('2sigma_1y', info['stats']['2sigma'])
                        sigma_3_1y = info['stats'].get('3sigma_1y', info['stats']['3sigma'])
                        
                        # 시그마 하락시 가격 계산
                        price_at_1sigma = base_close * (1 + sigma_1_1y / 100)
                        price_at_2sigma = base_close * (1 + sigma_2_1y / 100)
                        price_at_3sigma = base_close * (1 + sigma_3_1y / 100)
                        
                        current_prices_us.append({
                            '종목': f"{info['name']} ({symbol})",
                            '기준 종가': f"${base_close:,.2f}",
                            '기준일': base_date if base_date else '-',
                            '1σ(1년)': f"{sigma_1_1y:.2f}%",
                            '1σ 하락시 가격': f"${price_at_1sigma:,.2f}",
                            '2σ(1년)': f"{sigma_2_1y:.2f}%",
                            '2σ 하락시 가격': f"${price_at_2sigma:,.2f}",
                            '3σ(1년)': f"{sigma_3_1y:.2f}%",
                            '3σ 하락시 가격': f"${price_at_3sigma:,.2f}"
                        })
                    except Exception as e:
                        st.error(f"{symbol} 오류: {str(e)}")
                
                if current_prices_us:
                    df_current_us = pd.DataFrame(current_prices_us)
                    # 선택 가능한 DataFrame으로 표시
                    selected_us = st.dataframe(
                        df_current_us, 
                        use_container_width=True, 
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row"
                    )
                    
                    # 선택된 행이 있으면 분석 실행
                    if selected_us and len(selected_us.selection.rows) > 0:
                        selected_idx = selected_us.selection.rows[0]
                        selected_stock = df_current_us.iloc[selected_idx]
                        symbol = selected_stock['종목'].split('(')[-1].rstrip(')')
                        
                        # 선택된 종목 정보 표시
                        st.markdown(f"**선택된 종목: {selected_stock['종목']}**")
                        
                        # 버튼을 동일한 행에 배치
                        col_analyze, col_delete = st.columns(2)
                        
                        with col_analyze:
                            # 분석 결과 탭으로 이동 버튼
                            if st.button("📊 분석 결과 보기", key=f"analyze_us_{symbol}", use_container_width=True):
                                # 선택된 종목의 데이터를 분석 결과에 설정
                                if symbol in st.session_state.monitoring_stocks:
                                    stock_info = st.session_state.monitoring_stocks[symbol]
                                    analyzer = StockAnalyzer()
                                    
                                    # 종목 데이터 가져오기
                                    df = analyzer.get_stock_data(symbol, stock_info['type'])
                                    if df is not None:
                                        # 분석 결과를 세션에 저장
                                        st.session_state.current_analysis = {
                                            'symbol': symbol,
                                            'name': stock_info['name'],
                                            'type': stock_info['type'],
                                            'df': df,
                                            'stats': stock_info['stats']
                                        }
                                        st.success(f"{selected_stock['종목']} 분석 데이터가 로드되었습니다!")
                                        st.rerun()
                        
                        with col_delete:
                            # 삭제 버튼
                            if st.button(f"🗑️ 삭제", key=f"delete_us_{symbol}", use_container_width=True):
                                if symbol in st.session_state.monitoring_stocks:
                                    del st.session_state.monitoring_stocks[symbol]
                                    save_stocks_to_sheets()
                                    st.success(f"{selected_stock['종목']} 삭제 완료!")
                                    st.rerun()
            else:
                st.info("저장된 미국 주식이 없습니다.")
    else:
        st.info("📝 저장된 종목이 없습니다. 사이드바에서 종목을 추가해보세요!")

# 탭 3: 백테스팅
with tab3:
    st.subheader("📈 백테스팅")
    
    if 'current_analysis' in st.session_state:
        analysis = st.session_state.current_analysis
        selected_symbol = analysis['symbol']
        st.info(f"📊 백테스팅 종목: {analysis['name']} ({analysis['symbol']})")
    else:
        st.info("📊 먼저 탭 1에서 종목을 검색하고 분석해주세요.")
        selected_symbol = None
    
    # 투자 금액 설정
    st.markdown("**투자 금액 설정**")
    col1_1, col1_2, col1_3 = st.columns(3)
    
    with col1_1:
        amount_1sigma = st.number_input("1σ 하락시", min_value=0, value=100)
    with col1_2:
        amount_2sigma = st.number_input("2σ 하락시", min_value=0, value=100)
    with col1_3:
        amount_3sigma = st.number_input("3σ 하락시", min_value=0, value=100)
    
# 백테스팅 실행 버튼
    if st.button("🚀 백테스팅 실행", use_container_width=True, type="primary"):
        if selected_symbol:
            # 백테스팅 실행
            analyzer = StockAnalyzer()
            
            # 데이터 가져오기
            if 'current_analysis' in st.session_state:
                df = st.session_state.current_analysis['df']
                analysis = st.session_state.current_analysis
            else:
                st.error("분석 데이터가 없습니다.")
                st.stop()
            
            # 미국 주식인지 확인
            is_us_stock = analysis['type'] == 'US'
            
            # 1년과 5년 데이터 모두 준비
            df_1year = df.tail(252)  # 1년 데이터
            df_5year = df  # 5년 데이터
            
            # 시그마 레벨 가져오기
            stats = analysis['stats']
            sigma_1 = stats['1sigma']
            sigma_2 = stats['2sigma']
            sigma_3 = stats['3sigma']
            
            # 백테스팅 함수 정의 (수정됨)
            def run_backtest(df_data, period_name, include_1sigma=True):
                buy_history = []
                total_investment = 0
                total_shares = 0
                
                for i in range(1, len(df_data)):
                    current_return = df_data['Returns'].iloc[i]
                    current_price = df_data['Close'].iloc[i]
                    current_date = df_data.index[i]
                    
                    investment = 0  # 기본값 초기화
                    sigma_level = None
                    
                    # 3σ 하락 시 (가장 큰 하락 우선 체크)
                    if current_return <= sigma_3:
                        investment = amount_3sigma
                        sigma_level = '3σ'
                    # 2σ 하락 시
                    elif current_return <= sigma_2:
                        investment = amount_2sigma
                        sigma_level = '2σ'
                    # 1σ 하락 시 (include_1sigma가 True일 때만)
                    elif include_1sigma and current_return <= sigma_1:
                        investment = amount_1sigma
                        sigma_level = '1σ'
                    
                    # 매수 실행
                    if investment > 0:
                        # 한국 주식의 경우 만원 단위 처리 (여기서 한 번만)
                        if not is_us_stock:
                            investment = investment * 10000  # 만원을 원으로 변환
                        
                        shares = investment / current_price
                        buy_history.append({
                            'date': current_date,
                            'price': current_price,
                            'return': current_return,
                            'sigma_level': sigma_level,
                            'investment': investment,
                            'shares': shares
                        })
                        total_investment += investment
                        total_shares += shares
                
                # 결과 계산
                if buy_history:
                    avg_price = total_investment / total_shares
                    current_price = df_data['Close'].iloc[-1]
                    current_value = total_shares * current_price
                    total_return = ((current_value - total_investment) / total_investment) * 100
                    
                    return {
                        'buy_history': buy_history,
                        'buy_count': len(buy_history),
                        'total_investment': total_investment,
                        'total_shares': total_shares,
                        'avg_price': avg_price,
                        'current_value': current_value,
                        'total_return': total_return
                    }
                else:
                    return {
                        'buy_history': [],
                        'buy_count': 0,
                        'total_investment': 0,
                        'total_shares': 0,
                        'avg_price': 0,
                        'current_value': 0,
                        'total_return': 0
                    }
            
            # DCA 전략 계산 (수정됨)
            def run_dca_comparison(df_data, period_months):
                # 매월 고정 투자금 설정
                if is_us_stock:
                    monthly_amount = 100  # 매월 $100
                else:
                    monthly_amount = 100000  # 매월 10만원 (원 단위)
                
                # DCA 투자 변수 초기화
                dca_investment = 0
                dca_shares = 0
                dca_buy_count = 0
                dca_buy_history = []
                
                # 매월 투자 로직 (수정됨)
                found_months = 0
                last_year_month = None
                
                for i in range(len(df_data)):
                    if found_months >= period_months:
                        break
                        
                    current_date = df_data.index[i]
                    current_year_month = (current_date.year, current_date.month)
                    
                    # 새로운 월이고, 10일 이후인 첫 거래일
                    if (current_date.day >= 10 and 
                        current_year_month != last_year_month):
                        
                        current_price = df_data['Close'].iloc[i]
                        shares = monthly_amount / current_price
                        
                        dca_investment += monthly_amount
                        dca_shares += shares
                        dca_buy_count += 1
                        
                        dca_buy_history.append({
                            'date': current_date,
                            'price': current_price,
                            'investment': monthly_amount,
                            'shares': shares
                        })
                        
                        found_months += 1
                        last_year_month = current_year_month
                
                # 현재 가격으로 결과 계산
                if dca_shares > 0:
                    current_price = df_data['Close'].iloc[-1]
                    dca_current_value = dca_shares * current_price
                    dca_total_return = ((dca_current_value - dca_investment) / dca_investment) * 100
                    dca_avg_price = dca_investment / dca_shares
                else:
                    dca_current_value = 0
                    dca_total_return = 0
                    dca_avg_price = 0
                
                return {
                    'buy_count': dca_buy_count,
                    'total_investment': dca_investment,
                    'monthly_amount': monthly_amount,
                    'avg_price': dca_avg_price,
                    'total_shares': dca_shares,
                    'current_value': dca_current_value,
                    'total_return': dca_total_return,
                    'buy_history': dca_buy_history
                }
            
            # 백테스팅 실행
            with st.spinner("백테스팅 분석 중..."):
                # 1σ 전략 (1년, 5년)
                results_1sigma_1year = run_backtest(df_1year, "1년", include_1sigma=True)
                results_1sigma_5year = run_backtest(df_5year, "5년", include_1sigma=True)
                
                # 2σ 전략 (1년, 5년)
                results_2sigma_1year = run_backtest(df_1year, "1년", include_1sigma=False)
                results_2sigma_5year = run_backtest(df_5year, "5년", include_1sigma=False)
                
                # DCA 비교 (1년=12개월, 5년=60개월)
                comparison_1y = {'dca': run_dca_comparison(df_1year, 12)}
                comparison_5y = {'dca': run_dca_comparison(df_5year, 60)}
            
            # 결과를 세션에 저장 (핵심 수정 부분!)
            st.session_state.update({
                'backtest_completed': True,
                'backtest_results': {
                    'results_1sigma_1year': results_1sigma_1year,
                    'results_1sigma_5year': results_1sigma_5year,
                    'results_2sigma_1year': results_2sigma_1year,
                    'results_2sigma_5year': results_2sigma_5year,
                    'comparison_1y': comparison_1y,
                    'comparison_5y': comparison_5y,
                    'df_1year': df_1year,
                    'df_5year': df_5year,
                    'stats': stats,
                    'sigma_1': sigma_1,
                    'sigma_2': sigma_2,
                    'is_us_stock': is_us_stock
                },
                # 몬테카를로에서 사용할 데이터도 함께 저장
                'results_1sigma_1year': results_1sigma_1year,
                'results_1sigma_5year': results_1sigma_5year,
                'results_2sigma_1year': results_2sigma_1year,
                'results_2sigma_5year': results_2sigma_5year,
                'comparison_1y': comparison_1y,
                'comparison_5y': comparison_5y,
                'df_1year': df_1year,
                'df_5year': df_5year,
                'is_us_stock': is_us_stock,
                'stats': stats
            })
            
            # 즉시 결과 표시를 위해 페이지 새로고침
            st.rerun()
    
    # 백테스팅 결과가 있으면 표시
    if st.session_state.get('backtest_completed', False):
        # 세션에서 결과 불러오기
        backtest_data = st.session_state['backtest_results']
        results_1sigma_1year = backtest_data['results_1sigma_1year']
        results_1sigma_5year = backtest_data['results_1sigma_5year']
        results_2sigma_1year = backtest_data['results_2sigma_1year']
        results_2sigma_5year = backtest_data['results_2sigma_5year']
        comparison_1y = backtest_data['comparison_1y']
        comparison_5y = backtest_data['comparison_5y']
        df_5year = backtest_data['df_5year']
        df_1year = backtest_data['df_1year']
        stats = backtest_data['stats']
        sigma_1 = backtest_data['sigma_1']
        sigma_2 = backtest_data['sigma_2']
        is_us_stock = backtest_data['is_us_stock']
        dca_1y = comparison_1y['dca']
        dca_5y = comparison_5y['dca']
        
        # 결과 표시
        st.success("✅ 백테스팅 완료!")
        
        # 3가지 전략 비교 섹션 (일시불 제외)
        st.markdown("#### 📊 투자 전략 백테스팅 결과")
        
        # 1σ 전략
        st.markdown("---")
        st.markdown("### 1️⃣ 1σ 이상 하락시 매수 전략")
        
        col_1s_1y, col_1s_5y = st.columns(2)
        
        with col_1s_1y:
            st.markdown("**📅 최근 1년**")
            if results_1sigma_1year['buy_count'] > 0:
                # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("매수 횟수", f"{results_1sigma_1year['buy_count']}회")
                with col2:
                    if is_us_stock:
                        st.metric("평균 매수 단가", f"${results_1sigma_1year['avg_price']:,.2f}")
                    else:
                        st.metric("평균 매수 단가", f"₩{results_1sigma_1year['avg_price']:,.0f}")
                with col3:
                    st.metric("보유 주식수", f"{results_1sigma_1year['total_shares']:.2f}주")
                
                # 둘째 행: 총 투자금, 수익률
                col4, col5 = st.columns(2)
                with col4:
                    if is_us_stock:
                        st.metric("총 투자금", f"${results_1sigma_1year['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{results_1sigma_1year['total_investment']:,.0f}")
                with col5:
                    st.metric("수익률", f"{results_1sigma_1year['total_return']:+.2f}%",
                             delta=f"{results_1sigma_1year['total_return']:+.2f}%")
                
                # 매수 내역
                with st.expander(f"📋 매수 내역 ({results_1sigma_1year['buy_count']}건)"):
                    buy_df = pd.DataFrame(results_1sigma_1year['buy_history'])
                    buy_df['날짜'] = buy_df['date'].dt.strftime('%Y.%m.%d')
                    if is_us_stock:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"${x:,.2f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"${x:,.0f}")
                    else:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"₩{x:,.0f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                    buy_df['수익률'] = buy_df['return'].apply(lambda x: f"{x:.2f}%")
                    buy_df['시그마'] = buy_df['sigma_level']
                    display_df = buy_df[['날짜', '가격', '수익률', '시그마', '투자금']]
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("매수 내역 없음")
        
        with col_1s_5y:
            st.markdown("**📅 최근 5년**")
            if results_1sigma_5year['buy_count'] > 0:
                # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("매수 횟수", f"{results_1sigma_5year['buy_count']}회")
                with col2:
                    if is_us_stock:
                        st.metric("평균 매수 단가", f"${results_1sigma_5year['avg_price']:,.2f}")
                    else:
                        st.metric("평균 매수 단가", f"₩{results_1sigma_5year['avg_price']:,.0f}")
                with col3:
                    st.metric("보유 주식수", f"{results_1sigma_5year['total_shares']:.2f}주")
                
                # 둘째 행: 총 투자금, 수익률
                col4, col5 = st.columns(2)
                with col4:
                    if is_us_stock:
                        st.metric("총 투자금", f"${results_1sigma_5year['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{results_1sigma_5year['total_investment']:,.0f}")
                with col5:
                    st.metric("수익률", f"{results_1sigma_5year['total_return']:+.2f}%",
                             delta=f"{results_1sigma_5year['total_return']:+.2f}%")
                
                # 매수 내역
                with st.expander(f"📋 매수 내역 ({results_1sigma_5year['buy_count']}건)"):
                    buy_df = pd.DataFrame(results_1sigma_5year['buy_history'])
                    buy_df['날짜'] = buy_df['date'].dt.strftime('%Y.%m.%d')
                    if is_us_stock:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"${x:,.2f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"${x:,.0f}")
                    else:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"₩{x:,.0f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                    buy_df['수익률'] = buy_df['return'].apply(lambda x: f"{x:.2f}%")
                    buy_df['시그마'] = buy_df['sigma_level']
                    display_df = buy_df[['날짜', '가격', '수익률', '시그마', '투자금']]
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("매수 내역 없음")
        
        # 2σ 전략
        st.markdown("---")
        st.markdown("### 2️⃣ 2σ 이상 하락시 매수 전략")
        
        col_2s_1y, col_2s_5y = st.columns(2)
        
        with col_2s_1y:
            st.markdown("**📅 최근 1년**")
            if results_2sigma_1year['buy_count'] > 0:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("매수 횟수", f"{results_2sigma_1year['buy_count']}회")
                with col2:
                    if is_us_stock:
                        st.metric("평균 매수 단가", f"${results_2sigma_1year['avg_price']:,.2f}")
                    else:
                        st.metric("평균 매수 단가", f"₩{results_2sigma_1year['avg_price']:,.0f}")
                with col3:
                    st.metric("보유 주식수", f"{results_2sigma_1year['total_shares']:.2f}주")
                
                col4, col5 = st.columns(2)
                with col4:
                    if is_us_stock:
                        st.metric("총 투자금", f"${results_2sigma_1year['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{results_2sigma_1year['total_investment']:,.0f}")
                with col5:
                    st.metric("수익률", f"{results_2sigma_1year['total_return']:+.2f}%",
                             delta=f"{results_2sigma_1year['total_return']:+.2f}%")
                
                with st.expander(f"📋 매수 내역 ({results_2sigma_1year['buy_count']}건)"):
                    buy_df = pd.DataFrame(results_2sigma_1year['buy_history'])
                    buy_df['날짜'] = buy_df['date'].dt.strftime('%Y.%m.%d')
                    if is_us_stock:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"${x:,.2f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"${x:,.0f}")
                    else:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"₩{x:,.0f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                    buy_df['수익률'] = buy_df['return'].apply(lambda x: f"{x:.2f}%")
                    buy_df['시그마'] = buy_df['sigma_level']
                    display_df = buy_df[['날짜', '가격', '수익률', '시그마', '투자금']]
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("매수 내역 없음")
        
        with col_2s_5y:
            st.markdown("**📅 최근 5년**")
            if results_2sigma_5year['buy_count'] > 0:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("매수 횟수", f"{results_2sigma_5year['buy_count']}회")
                with col2:
                    if is_us_stock:
                        st.metric("평균 매수 단가", f"${results_2sigma_5year['avg_price']:,.2f}")
                    else:
                        st.metric("평균 매수 단가", f"₩{results_2sigma_5year['avg_price']:,.0f}")
                with col3:
                    st.metric("보유 주식수", f"{results_2sigma_5year['total_shares']:.2f}주")
                
                col4, col5 = st.columns(2)
                with col4:
                    if is_us_stock:
                        st.metric("총 투자금", f"${results_2sigma_5year['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{results_2sigma_5year['total_investment']:,.0f}")
                with col5:
                    st.metric("수익률", f"{results_2sigma_5year['total_return']:+.2f}%",
                             delta=f"{results_2sigma_5year['total_return']:+.2f}%")
                
                with st.expander(f"📋 매수 내역 ({results_2sigma_5year['buy_count']}건)"):
                    buy_df = pd.DataFrame(results_2sigma_5year['buy_history'])
                    buy_df['날짜'] = buy_df['date'].dt.strftime('%Y.%m.%d')
                    if is_us_stock:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"${x:,.2f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"${x:,.0f}")
                    else:
                        buy_df['가격'] = buy_df['price'].apply(lambda x: f"₩{x:,.0f}")
                        buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                    buy_df['수익률'] = buy_df['return'].apply(lambda x: f"{x:.2f}%")
                    buy_df['시그마'] = buy_df['sigma_level']
                    display_df = buy_df[['날짜', '가격', '수익률', '시그마', '투자금']]
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("매수 내역 없음")
        
        # DCA 전략
        st.markdown("---")
        st.markdown("### 3️⃣ DCA (매월 정액 투자)")

        col_dca_1y, col_dca_5y = st.columns(2)
        
        with col_dca_1y:
            st.markdown("**📅 최근 1년**")
            if dca_1y['buy_count'] > 0:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("매수 횟수", f"{dca_1y['buy_count']}회")
                with col2:
                    if is_us_stock:
                        st.metric("평균 매수 단가", f"${dca_1y['avg_price']:,.2f}")
                    else:
                        st.metric("평균 매수 단가", f"₩{dca_1y['avg_price']:,.0f}")
                with col3:
                    st.metric("보유 주식수", f"{dca_1y['total_shares']:.2f}주")
                
                col4, col5 = st.columns(2)
                with col4:
                    if is_us_stock:
                        st.metric("총 투자금", f"${dca_1y['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{dca_1y['total_investment']:,.0f}")
                with col5:
                    st.metric("수익률", f"{dca_1y['total_return']:+.2f}%",
                             delta=f"{dca_1y['total_return']:+.2f}%")
                
                with st.expander(f"📋 매수 내역 ({dca_1y['buy_count']}건)"):
                    if dca_1y['buy_history']:
                        dca_df = pd.DataFrame(dca_1y['buy_history'])
                        dca_df['날짜'] = dca_df['date'].dt.strftime('%Y.%m.%d')
                        if is_us_stock:
                            dca_df['가격'] = dca_df['price'].apply(lambda x: f"${x:,.2f}")
                            dca_df['투자금'] = dca_df['investment'].apply(lambda x: f"${x:,.0f}")
                        else:
                            dca_df['가격'] = dca_df['price'].apply(lambda x: f"₩{x:,.0f}")
                            dca_df['투자금'] = dca_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                        dca_df['주식수'] = dca_df['shares'].apply(lambda x: f"{x:.2f}주")
                        display_dca_df = dca_df[['날짜', '가격', '투자금', '주식수']]
                        st.dataframe(display_dca_df, use_container_width=True, hide_index=True)
            else:
                st.info("매수 내역 없음")
        
        with col_dca_5y:
            st.markdown("**📅 최근 5년**")
            if dca_5y['buy_count'] > 0:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("매수 횟수", f"{dca_5y['buy_count']}회")
                with col2:
                    if is_us_stock:
                        st.metric("평균 매수 단가", f"${dca_5y['avg_price']:,.2f}")
                    else:
                        st.metric("평균 매수 단가", f"₩{dca_5y['avg_price']:,.0f}")
                with col3:
                    st.metric("보유 주식수", f"{dca_5y['total_shares']:.2f}주")
                
                col4, col5 = st.columns(2)
                with col4:
                    if is_us_stock:
                        st.metric("총 투자금", f"${dca_5y['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{dca_5y['total_investment']:,.0f}")
                with col5:
                    st.metric("수익률", f"{dca_5y['total_return']:+.2f}%",
                             delta=f"{dca_5y['total_return']:+.2f}%")
                
                with st.expander(f"📋 매수 내역 ({dca_5y['buy_count']}건)"):
                    if dca_5y['buy_history']:
                        dca_df = pd.DataFrame(dca_5y['buy_history'])
                        dca_df['날짜'] = dca_df['date'].dt.strftime('%Y.%m.%d')
                        if is_us_stock:
                            dca_df['가격'] = dca_df['price'].apply(lambda x: f"${x:,.2f}")
                            dca_df['투자금'] = dca_df['investment'].apply(lambda x: f"${x:,.0f}")
                        else:
                            dca_df['가격'] = dca_df['price'].apply(lambda x: f"₩{x:,.0f}")
                            dca_df['투자금'] = dca_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                        dca_df['주식수'] = dca_df['shares'].apply(lambda x: f"{x:.2f}주")
                        display_dca_df = dca_df[['날짜', '가격', '투자금', '주식수']]
                        st.dataframe(display_dca_df, use_container_width=True, hide_index=True)

        # 수익률 비교 그래프
        st.markdown("---")
        st.markdown("#### 📊 투자 효율 비교 (100만원당 수익률)")
        
        col_graph_1y, col_graph_5y = st.columns(2)
        
        # 1년 결과 그래프
        with col_graph_1y:
            st.markdown("**1년 투자 효율 비교**")
            
            efficiency_1y = []
            labels_1y = []
            
            if results_1sigma_1year['total_investment'] > 0:
                efficiency_1y.append(results_1sigma_1year['total_return'])
            else:
                efficiency_1y.append(0)
            labels_1y.append('1σ 전략')
            
            if results_2sigma_1year['total_investment'] > 0:
                efficiency_1y.append(results_2sigma_1year['total_return'])
            else:
                efficiency_1y.append(0)
            labels_1y.append('2σ 전략')
            
            efficiency_1y.append(comparison_1y['dca']['total_return'])
            labels_1y.append('DCA')
            
            fig_1y = go.Figure()
            fig_1y.add_trace(go.Bar(
                x=labels_1y,
                y=efficiency_1y,
                text=[f'{e:+.2f}%' for e in efficiency_1y],
                textposition='auto',
                marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
            ))
            fig_1y.update_layout(
                title="1년 투자 효율",
                xaxis_title="투자 전략",
                yaxis_title="수익률 (%)",
                height=400,
                showlegend=False
            )
            st.plotly_chart(fig_1y, use_container_width=True)
        
        # 5년 결과 그래프
        with col_graph_5y:
            st.markdown("**5년 투자 효율 비교**")
            
            efficiency_5y = []
            labels_5y = []
            
            if results_1sigma_5year['total_investment'] > 0:
                efficiency_5y.append(results_1sigma_5year['total_return'])
            else:
                efficiency_5y.append(0)
            labels_5y.append('1σ 전략')
            
            if results_2sigma_5year['total_investment'] > 0:
                efficiency_5y.append(results_2sigma_5year['total_return'])
            else:
                efficiency_5y.append(0)
            labels_5y.append('2σ 전략')
            
            efficiency_5y.append(comparison_5y['dca']['total_return'])
            labels_5y.append('DCA')
            
            fig_5y = go.Figure()
            fig_5y.add_trace(go.Bar(
                x=labels_5y,
                y=efficiency_5y,
                text=[f'{e:+.2f}%' for e in efficiency_5y],
                textposition='auto',
                marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
            ))
            fig_5y.update_layout(
                title="5년 투자 효율",
                xaxis_title="투자 전략",
                yaxis_title="수익률 (%)",
                height=400,
                showlegend=False
            )
            st.plotly_chart(fig_5y, use_container_width=True)
        
    # ============= 시그마별 매수 비율 최적화 섹션 =============
    st.markdown("---")
    st.markdown("## 🎲 시그마별 매수 금액 비율 최적화")
    st.markdown("1σ, 2σ, 3σ 하락 시 각각 얼마씩 매수해야 최적의 수익률을 얻을 수 있는지 찾아봅시다.")

    # 최적화를 위한 백테스팅 함수
    def backtest_sigma_ratio(df_data, ratio_1s, ratio_2s, ratio_3s, base_amount=100):
        """
        시그마별 매수 비율에 따른 백테스팅
        ratio_1s: 1시그마 하락시 매수 금액 비율
        ratio_2s: 2시그마 하락시 매수 금액 비율  
        ratio_3s: 3시그마 하락시 매수 금액 비율
        base_amount: 기본 매수 단위
        """
        
        # 일별 수익률로 시그마 계산
        daily_returns = df_data['Close'].pct_change().dropna()
        mean_return = daily_returns.mean()
        std_return = daily_returns.std()
        
        sigma_1 = mean_return - 1 * std_return
        sigma_2 = mean_return - 2 * std_return
        sigma_3 = mean_return - 3 * std_return
        
        # 백테스팅
        total_investment = 0
        total_shares = 0
        buy_history = []
        
        for i in range(1, len(df_data)):
            current_return = (df_data['Close'].iloc[i] - df_data['Close'].iloc[i-1]) / df_data['Close'].iloc[i-1]
            current_price = df_data['Close'].iloc[i]
            current_date = df_data.index[i]
            
            buy_amount = 0
            
            # 3시그마 하락 (가장 큰 하락)
            if current_return <= sigma_3:
                buy_amount = base_amount * ratio_3s
                buy_history.append({
                    'date': current_date,
                    'type': '3σ',
                    'price': current_price,
                    'amount': buy_amount
                })
            # 2시그마 하락
            elif current_return <= sigma_2:
                buy_amount = base_amount * ratio_2s
                buy_history.append({
                    'date': current_date,
                    'type': '2σ',
                    'price': current_price,
                    'amount': buy_amount
                })
            # 1시그마 하락
            elif current_return <= sigma_1:
                buy_amount = base_amount * ratio_1s
                buy_history.append({
                    'date': current_date,
                    'type': '1σ',
                    'price': current_price,
                    'amount': buy_amount
                })
            
            if buy_amount > 0:
                shares = buy_amount / current_price
                total_shares += shares
                total_investment += buy_amount
        
        # 최종 수익률 계산
        if total_investment > 0:
            final_value = total_shares * df_data['Close'].iloc[-1]
            total_return = ((final_value - total_investment) / total_investment) * 100
            avg_price = total_investment / total_shares if total_shares > 0 else 0
            
            # 시그마별 매수 횟수 계산
            buy_counts = {'1σ': 0, '2σ': 0, '3σ': 0}
            buy_amounts = {'1σ': 0, '2σ': 0, '3σ': 0}
            
            for buy in buy_history:
                buy_counts[buy['type']] += 1
                buy_amounts[buy['type']] += buy['amount']
            
            return {
                'total_return': total_return,
                'total_investment': total_investment,
                'avg_price': avg_price,
                'buy_counts': buy_counts,
                'buy_amounts': buy_amounts,
                'buy_history': buy_history,
                'final_value': final_value,
                'total_shares': total_shares
            }
        else:
            return {
                'total_return': 0,
                'total_investment': 0,
                'avg_price': 0,
                'buy_counts': {'1σ': 0, '2σ': 0, '3σ': 0},
                'buy_amounts': {'1σ': 0, '2σ': 0, '3σ': 0},
                'buy_history': [],
                'final_value': 0,
                'total_shares': 0
            }

    # 몬테카를로 시뮬레이션 함수
    def monte_carlo_ratio_optimization(df_data, num_simulations=1000):
        """
        몬테카를로 시뮬레이션으로 최적의 시그마별 매수 비율 찾기
        """
        
        best_result = {
            'ratio': (0, 0, 0),
            'return': -999,
            'details': None
        }
        
        all_results = []
        
        # 다양한 비율 조합 테스트
        for _ in range(num_simulations):
            # 랜덤 비율 생성 (1~10 범위)
            ratio_1s = np.random.uniform(0.5, 5)
            ratio_2s = np.random.uniform(0.5, 8)
            ratio_3s = np.random.uniform(0.5, 10)
            
            # 백테스팅 실행
            result = backtest_sigma_ratio(df_data, ratio_1s, ratio_2s, ratio_3s)
            
            all_results.append({
                'ratio_1s': ratio_1s,
                'ratio_2s': ratio_2s,
                'ratio_3s': ratio_3s,
                'return': result['total_return'],
                'investment': result['total_investment'],
                'details': result
            })
            
            # 최고 수익률 업데이트
            if result['total_return'] > best_result['return']:
                best_result = {
                    'ratio': (ratio_1s, ratio_2s, ratio_3s),
                    'return': result['total_return'],
                    'details': result
                }
        
        return best_result, all_results

    # 사전 정의된 비율 테스트
    st.markdown("### 📊 사전 정의 비율 테스트")

    predefined_ratios = [
        ("보수적 (1:1.5:2)", 1, 1.5, 2),
        ("균형형 (1:2:3)", 1, 2, 3),
        ("균형형2 (1:2:4)", 1, 2, 4),
        ("공격적 (1:3:5)", 1, 3, 5),
        ("초공격적 (1:4:8)", 1, 4, 8),
        ("선형 증가 (1:2.5:4)", 1, 2.5, 4),
        ("지수 증가 (1:3:9)", 1, 3, 9)
    ]

    # 1년, 5년 데이터 모두 테스트
    test_periods = [
        ("1년", df_1year),
        ("5년", df_5year)
    ]

    # 테스트 실행 버튼
    if st.button("📈 비율 테스트 실행", type="primary", use_container_width=True):
        with st.spinner("다양한 비율 조합을 테스트 중..."):
            
            # 각 기간별로 테스트
            for period_name, period_data in test_periods:
                st.markdown(f"#### {period_name} 결과")
                
                results_list = []
                
                for name, r1, r2, r3 in predefined_ratios:
                    result = backtest_sigma_ratio(period_data, r1, r2, r3)
                    
                    # 정규화된 비율 문자열
                    normalized = f"{r1:.0f}:{r2:.0f}:{r3:.0f}"
                    
                    results_list.append({
                        '전략': name,
                        '비율': normalized,
                        '총 수익률': f"{result['total_return']:.2f}%",
                        '1σ 매수': result['buy_counts']['1σ'],
                        '2σ 매수': result['buy_counts']['2σ'],
                        '3σ 매수': result['buy_counts']['3σ'],
                        '평균 매수가': f"${result['avg_price']:.2f}" if is_us_stock else f"₩{result['avg_price']:,.0f}"
                    })
                
                # 데이터프레임으로 표시
                df_results = pd.DataFrame(results_list)
                st.dataframe(df_results, use_container_width=True, hide_index=True)
                
                # 최고 수익률 전략 하이라이트
                best_idx = df_results['총 수익률'].apply(lambda x: float(x.strip('%'))).idxmax()
                best_strategy = df_results.loc[best_idx, '전략']
                best_return = df_results.loc[best_idx, '총 수익률']
                
                st.success(f"✅ {period_name} 최고 수익률: **{best_strategy}** - {best_return}")

    # 몬테카를로 최적화
    st.markdown("---")
    st.markdown("### 🎯 몬테카를로 최적화")
    st.info("1,000개의 랜덤 비율 조합을 테스트하여 최적의 비율을 찾습니다.")

    col_mc1, col_mc2 = st.columns(2)

    with col_mc1:
        period_option = st.selectbox(
            "분석 기간 선택",
            ["1년", "5년"],
            key="mc_period"
        )

    with col_mc2:
        num_simulations = st.slider(
            "시뮬레이션 횟수",
            min_value=100,
            max_value=5000,
            value=1000,
            step=100,
            key="mc_simulations"
        )

    if st.button("🚀 최적 비율 찾기", type="secondary", use_container_width=True):
        with st.spinner(f"{num_simulations:,}개 조합 테스트 중..."):
            
            # 선택된 기간 데이터
            selected_data = df_1year if period_option == "1년" else df_5year
            
            # 몬테카를로 실행
            progress_bar = st.progress(0)
            best_result, all_results = monte_carlo_ratio_optimization(selected_data, num_simulations)
            progress_bar.progress(100)
            
            # 최적 비율 표시
            st.success("✅ 최적 비율 발견!")
            
            col_opt1, col_opt2, col_opt3, col_opt4 = st.columns(4)
            
            with col_opt1:
                st.metric("1σ 매수 비율", f"{best_result['ratio'][0]:.2f}x")
            
            with col_opt2:
                st.metric("2σ 매수 비율", f"{best_result['ratio'][1]:.2f}x")
            
            with col_opt3:
                st.metric("3σ 매수 비율", f"{best_result['ratio'][2]:.2f}x")
            
            with col_opt4:
                st.metric("예상 수익률", f"{best_result['return']:.2f}%")
            
            # 정규화된 비율 (가장 작은 값을 1로)
            min_ratio = min(best_result['ratio'])
            normalized_ratios = [r/min_ratio for r in best_result['ratio']]
            
            st.info(f"📊 정규화된 비율: **{normalized_ratios[0]:.1f} : {normalized_ratios[1]:.1f} : {normalized_ratios[2]:.1f}**")
            
            # 최적 비율 상세 정보
            st.markdown("### 📈 최적 비율 상세 분석")
            
            details = best_result['details']
            
            col_detail1, col_detail2, col_detail3 = st.columns(3)
            
            with col_detail1:
                st.markdown("**매수 횟수**")
                for sigma, count in details['buy_counts'].items():
                    st.write(f"• {sigma}: {count}회")
            
            with col_detail2:
                st.markdown("**매수 금액 비중**")
                total_amount = sum(details['buy_amounts'].values())
                if total_amount > 0:
                    for sigma, amount in details['buy_amounts'].items():
                        percentage = (amount / total_amount) * 100
                        st.write(f"• {sigma}: {percentage:.1f}%")
            
            with col_detail3:
                st.markdown("**투자 성과**")
                st.write(f"• 총 투자금: ${details['total_investment']:,.0f}")
                st.write(f"• 최종 가치: ${details['final_value']:,.0f}")
                st.write(f"• 평균 매수가: ${details['avg_price']:.2f}")
            
            # 시각화: 수익률 분포
            st.markdown("### 📊 시뮬레이션 결과 분포")
            
            # 수익률 분포 히스토그램
            returns = [r['return'] for r in all_results]
            
            fig_dist = go.Figure()
            
            fig_dist.add_trace(go.Histogram(
                x=returns,
                nbinsx=50,
                marker_color='lightblue',
                opacity=0.7,
                name='수익률 분포'
            ))
            
            # 최적 수익률 표시
            fig_dist.add_vline(
                x=best_result['return'],
                line_dash="dash",
                line_color="red",
                annotation_text=f"최적: {best_result['return']:.1f}%"
            )
            
            fig_dist.update_layout(
                title=f"{num_simulations:,}개 비율 조합의 수익률 분포",
                xaxis_title="수익률 (%)",
                yaxis_title="빈도",
                height=400
            )
            
            st.plotly_chart(fig_dist, use_container_width=True)
        
            # 실행 가이드
            st.markdown("### 💰 실전 적용 가이드")
            
            # 기본 투자 단위 설정
            if is_us_stock:
                base_unit = 100  # $100
                currency = "$"
            else:
                base_unit = 100000  # 10만원
                currency = "₩"
            
            st.markdown(f"**기본 매수 단위: {currency}{base_unit:,}**")
            
            col_guide1, col_guide2, col_guide3 = st.columns(3)
            
            with col_guide1:
                amount_1s = base_unit * best_result['ratio'][0]
                st.markdown("**1σ 하락 시**")
                st.write(f"{currency}{amount_1s:,.0f} 매수")
                st.caption(f"(기본 단위 × {best_result['ratio'][0]:.2f})")
            
            with col_guide2:
                amount_2s = base_unit * best_result['ratio'][1]
                st.markdown("**2σ 하락 시**")
                st.write(f"{currency}{amount_2s:,.0f} 매수")
                st.caption(f"(기본 단위 × {best_result['ratio'][1]:.2f})")
            
            with col_guide3:
                amount_3s = base_unit * best_result['ratio'][2]
                st.markdown("**3σ 하락 시**")
                st.write(f"{currency}{amount_3s:,.0f} 매수")
                st.caption(f"(기본 단위 × {best_result['ratio'][2]:.2f})")
            
            # 인사이트
            st.markdown("### 💡 핵심 인사이트")
            
            insights = []
            
            # 비율 패턴 분석
            ratio_pattern = best_result['ratio'][1] / best_result['ratio'][0]
            if ratio_pattern > 2.5:
                insights.append("📈 2σ 하락에 공격적으로 대응하는 전략이 효과적")
            elif ratio_pattern < 1.5:
                insights.append("📊 1σ와 2σ 하락을 비슷하게 취급하는 것이 효과적")
            
            # 3시그마 비중
            ratio_3s_pattern = best_result['ratio'][2] / best_result['ratio'][0]
            if ratio_3s_pattern > 5:
                insights.append("🎯 극단적 하락(3σ)에서 큰 베팅이 높은 수익률 창출")
            elif ratio_3s_pattern < 3:
                insights.append("⚖️ 극단적 하락에서도 과도한 베팅은 피하는 것이 유리")
            
            # 상위 10% 분석
            sorted_results = sorted(all_results, key=lambda x: x['return'], reverse=True)
            top_10_percent = sorted_results[:max(1, len(sorted_results)//10)]
            avg_top_ratios = [
                np.mean([r['ratio_1s'] for r in top_10_percent]),
                np.mean([r['ratio_2s'] for r in top_10_percent]),
                np.mean([r['ratio_3s'] for r in top_10_percent])
            ]
            
            insights.append(f"🏆 상위 10% 전략의 평균 비율: {avg_top_ratios[0]:.1f}:{avg_top_ratios[1]:.1f}:{avg_top_ratios[2]:.1f}")
            
            for insight in insights:
                st.info(insight)
            
            # 세션 스테이트에 저장
            st.session_state['optimal_sigma_ratios'] = best_result['ratio']
            st.session_state['optimal_sigma_return'] = best_result['return']

    # ============= 시그마 매수 횟수 디버깅 =============
    import streamlit as st
    import pandas as pd
    import numpy as np
    import plotly.graph_objects as go
    from datetime import datetime, timedelta

    st.title("🔍 시그마 매수 횟수 불일치 디버깅")

    # 데이터 로드 섹션
    st.markdown("## 1. 데이터 확인")
    st.info("먼저 동일한 데이터를 사용하고 있는지 확인합니다.")

    # 여기서 df_1year가 이미 로드되어 있다고 가정
    if 'df_1year' in locals():
        st.write(f"데이터 기간: {df_1year.index[0].date()} ~ {df_1year.index[-1].date()}")
        st.write(f"총 거래일 수: {len(df_1year)}")
        
        # 일별 수익률 계산
        df_1year['Daily_Return'] = df_1year['Close'].pct_change()
        
        # 시그마 값 계산 (두 가지 방식)
        st.markdown("## 2. 시그마 계산 방식 비교")
        
        # 방식 1: 전체 기간 고정 시그마
        mean_return_fixed = df_1year['Daily_Return'].mean()
        std_return_fixed = df_1year['Daily_Return'].std()
        
        sigma_1_fixed = mean_return_fixed - 1 * std_return_fixed
        sigma_2_fixed = mean_return_fixed - 2 * std_return_fixed
        sigma_3_fixed = mean_return_fixed - 3 * std_return_fixed
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("1σ 임계값", f"{sigma_1_fixed:.4f}")
        with col2:
            st.metric("2σ 임계값", f"{sigma_2_fixed:.4f}")
        with col3:
            st.metric("3σ 임계값", f"{sigma_3_fixed:.4f}")
        
        # 매수 신호 카운트 함수들
        st.markdown("## 3. 매수 횟수 계산 (여러 방식)")
        
        # 방식 1: 원본 1σ 전략 (1σ 이하 모든 하락)
        def count_1sigma_strategy(df, sigma_1):
            """1σ 이하 모든 하락에서 매수"""
            count = 0
            for i in range(1, len(df)):
                if df['Daily_Return'].iloc[i] <= sigma_1:
                    count += 1
            return count
        
        # 방식 2: 원본 2σ 전략 (2σ 이하 하락)
        def count_2sigma_strategy(df, sigma_2):
            """2σ 이하 모든 하락에서 매수"""
            count = 0
            for i in range(1, len(df)):
                if df['Daily_Return'].iloc[i] <= sigma_2:
                    count += 1
            return count
        
        # 방식 3: 구간별 독립 카운트 (비율 테스트용)
        def count_independent_sigmas(df, sigma_1, sigma_2, sigma_3):
            """각 시그마 구간별 독립 카운트"""
            count_1s = 0
            count_2s = 0
            count_3s = 0
            
            for i in range(1, len(df)):
                ret = df['Daily_Return'].iloc[i]
                
                if ret <= sigma_3:
                    count_3s += 1
                elif ret <= sigma_2:
                    count_2s += 1
                elif ret <= sigma_1:
                    count_1s += 1
            
            return count_1s, count_2s, count_3s
        
        # 방식 4: 상세 분석 (모든 경우)
        def detailed_analysis(df, sigma_1, sigma_2, sigma_3):
            """상세한 매수 신호 분석"""
            results = {
                'dates_1s': [],
                'dates_2s': [],
                'dates_3s': [],
                'returns_1s': [],
                'returns_2s': [],
                'returns_3s': []
            }
            
            for i in range(1, len(df)):
                date = df.index[i]
                ret = df['Daily_Return'].iloc[i]
                
                if ret <= sigma_3:
                    results['dates_3s'].append(date)
                    results['returns_3s'].append(ret)
                elif ret <= sigma_2:
                    results['dates_2s'].append(date)
                    results['returns_2s'].append(ret)
                elif ret <= sigma_1:
                    results['dates_1s'].append(date)
                    results['returns_1s'].append(ret)
            
            return results
        
        # 계산 실행
        st.markdown("### 📊 계산 결과")
        
        # 1σ, 2σ 전략 카운트
        count_1sigma_strat = count_1sigma_strategy(df_1year, sigma_1_fixed)
        count_2sigma_strat = count_2sigma_strategy(df_1year, sigma_2_fixed)
        
        # 독립 구간 카운트
        count_1s_only, count_2s_only, count_3s_only = count_independent_sigmas(
            df_1year, sigma_1_fixed, sigma_2_fixed, sigma_3_fixed
        )
        
        # 결과 표시
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**전략별 매수 횟수 (누적)**")
            st.write(f"• 1σ 전략 (1σ 이하 모든 하락): {count_1sigma_strat}회")
            st.write(f"• 2σ 전략 (2σ 이하 모든 하락): {count_2sigma_strat}회")
            
        with col2:
            st.markdown("**시그마 구간별 횟수 (독립)**")
            st.write(f"• 1σ만 해당: {count_1s_only}회")
            st.write(f"• 2σ만 해당: {count_2s_only}회")
            st.write(f"• 3σ 해당: {count_3s_only}회")
            st.write(f"• 2σ+3σ 합계: {count_2s_only + count_3s_only}회")
        
        # 불일치 분석
        st.markdown("### 🔍 불일치 분석")
        
        expected_1s = 24  # 카드에 표시된 값
        expected_2s = 9   # 카드에 표시된 값
        table_2s_3s = 7   # 테이블에 표시된 값 (6+1)
        
        diff_1s = count_1sigma_strat - expected_1s
        diff_2s = count_2sigma_strat - expected_2s
        diff_table = count_2s_only + count_3s_only - table_2s_3s
        
        if diff_1s != 0:
            st.warning(f"1σ 전략: 계산값 {count_1sigma_strat} vs 예상값 {expected_1s} (차이: {diff_1s})")
        else:
            st.success(f"✅ 1σ 전략 일치: {count_1sigma_strat}회")
        
        if diff_2s != 0:
            st.warning(f"2σ 전략: 계산값 {count_2sigma_strat} vs 예상값 {expected_2s} (차이: {diff_2s})")
        else:
            st.success(f"✅ 2σ 전략 일치: {count_2sigma_strat}회")
        
        if diff_table != 0:
            st.warning(f"테이블 2σ+3σ: 계산값 {count_2s_only + count_3s_only} vs 표시값 {table_2s_3s} (차이: {diff_table})")
        else:
            st.success(f"✅ 테이블 값 일치: {count_2s_only + count_3s_only}회")
        
        # 상세 분석
        st.markdown("## 4. 상세 매수 신호 분석")
        
        if st.button("상세 분석 실행"):
            details = detailed_analysis(df_1year, sigma_1_fixed, sigma_2_fixed, sigma_3_fixed)
            
            # 탭으로 구분
            tab1, tab2, tab3 = st.tabs(["1σ 구간", "2σ 구간", "3σ 구간"])
            
            with tab1:
                st.write(f"1σ 구간 매수 신호: {len(details['dates_1s'])}회")
                if details['dates_1s']:
                    df_1s = pd.DataFrame({
                        '날짜': details['dates_1s'],
                        '수익률': [f"{r*100:.2f}%" for r in details['returns_1s']]
                    })
                    st.dataframe(df_1s, use_container_width=True)
            
            with tab2:
                st.write(f"2σ 구간 매수 신호: {len(details['dates_2s'])}회")
                if details['dates_2s']:
                    df_2s = pd.DataFrame({
                        '날짜': details['dates_2s'],
                        '수익률': [f"{r*100:.2f}%" for r in details['returns_2s']]
                    })
                    st.dataframe(df_2s, use_container_width=True)
            
            with tab3:
                st.write(f"3σ 구간 매수 신호: {len(details['dates_3s'])}회")
                if details['dates_3s']:
                    df_3s = pd.DataFrame({
                        '날짜': details['dates_3s'],
                        '수익률': [f"{r*100:.2f}%" for r in details['returns_3s']]
                    })
                    st.dataframe(df_3s, use_container_width=True)
        
        # 시각화
        st.markdown("## 5. 시각화")
        
        # 수익률 분포와 시그마 선
        fig = go.Figure()
        
        # 히스토그램
        fig.add_trace(go.Histogram(
            x=df_1year['Daily_Return'].dropna(),
            name='일별 수익률 분포',
            nbinsx=50,
            marker_color='lightblue',
            opacity=0.7
        ))
        
        # 시그마 선 추가
        fig.add_vline(x=sigma_1_fixed, line_dash="dash", line_color="yellow", 
                    annotation_text=f"1σ ({sigma_1_fixed:.3f})")
        fig.add_vline(x=sigma_2_fixed, line_dash="dash", line_color="orange",
                    annotation_text=f"2σ ({sigma_2_fixed:.3f})")
        fig.add_vline(x=sigma_3_fixed, line_dash="dash", line_color="red",
                    annotation_text=f"3σ ({sigma_3_fixed:.3f})")
        
        fig.update_layout(
            title="일별 수익률 분포와 시그마 임계값",
            xaxis_title="일별 수익률",
            yaxis_title="빈도",
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 시계열 차트
        st.markdown("### 시계열 매수 신호")
        
        fig2 = go.Figure()
        
        # 가격 차트
        fig2.add_trace(go.Scatter(
            x=df_1year.index,
            y=df_1year['Close'],
            mode='lines',
            name='종가',
            line=dict(color='blue', width=1)
        ))
        
        # 매수 신호 표시
        for i in range(1, len(df_1year)):
            ret = df_1year['Daily_Return'].iloc[i]
            if ret <= sigma_3_fixed:
                fig2.add_vline(x=df_1year.index[i], line_color="red", opacity=0.3)
            elif ret <= sigma_2_fixed:
                fig2.add_vline(x=df_1year.index[i], line_color="orange", opacity=0.3)
            elif ret <= sigma_1_fixed:
                fig2.add_vline(x=df_1year.index[i], line_color="yellow", opacity=0.2)
        
        fig2.update_layout(
            title="가격 차트와 매수 신호",
            xaxis_title="날짜",
            yaxis_title="가격",
            height=400
        )
        
        st.plotly_chart(fig2, use_container_width=True)
        
        # 추가 체크사항
        st.markdown("## 6. 추가 확인 사항")
        
        # 경계값 처리 확인
        st.markdown("### 경계값 처리")
        edge_cases = 0
        for i in range(1, len(df_1year)):
            ret = df_1year['Daily_Return'].iloc[i]
            # 정확히 시그마 값과 같은 경우
            if abs(ret - sigma_1_fixed) < 0.0001 or abs(ret - sigma_2_fixed) < 0.0001:
                edge_cases += 1
        
        st.write(f"시그마 값과 거의 같은 경우: {edge_cases}회")
        
        # 데이터 품질 확인
        st.markdown("### 데이터 품질")
        nan_count = df_1year['Daily_Return'].isna().sum()
        st.write(f"결측치(NaN) 개수: {nan_count}")
        
        # 주말/공휴일 확인
        dates_diff = []
        for i in range(1, len(df_1year)):
            diff = (df_1year.index[i] - df_1year.index[i-1]).days
            if diff > 1:
                dates_diff.append((df_1year.index[i-1], df_1year.index[i], diff))
        
        if dates_diff:
            st.write(f"1일 초과 간격: {len(dates_diff)}개")
            if st.checkbox("간격 상세 보기"):
                for start, end, diff in dates_diff[:5]:  # 처음 5개만
                    st.write(f"  {start.date()} → {end.date()} ({diff}일 간격)")

    else:
        st.error("df_1year 데이터가 로드되지 않았습니다. 먼저 데이터를 로드해주세요.")

    # 해결 방안 제시
    st.markdown("## 💡 가능한 해결 방안")

    st.info("""
    **불일치 원인:**
    1. **시그마 계산 시점**: 전체 기간 vs 롤링 윈도우
    2. **데이터 범위**: 정확히 같은 날짜 범위인지
    3. **경계값 처리**: <= vs < 차이
    4. **매수 로직**: 누적 vs 독립 카운트

    **해결 방법:**
    1. 동일한 데이터 소스 사용 확인
    2. 시그마 계산 방식 통일
    3. 매수 조건 명확히 정의
    4. 디버깅 로그 추가하여 각 매수 시점 기록
    """)