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

# Google Sheets만 사용하므로 로컬 파일 경로 제거

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
        
        # 헤더 설정
        headers = ['종목코드', '종목명', '타입']
        worksheet.clear()
        worksheet.append_row(headers)
        
        # 데이터 추가
        for symbol, info in st.session_state.monitoring_stocks.items():
            row = [symbol, info['name'], info['type']]
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
            
            # 모든 값 가져오기 (캐시 무효화를 위해 강제로 새로고침)
            # worksheet를 새로 가져와서 캐싱 방지
            worksheet = spreadsheet.get_worksheet(0)
            all_values = worksheet.get_all_values()
            
            if len(all_values) <= 1:  # 헤더만 있거나 빈 경우
                st.info("Google Sheets에 저장된 데이터가 없습니다.")
                return True
            
            # 헤더 제외하고 데이터 처리
            stocks = {}
            for row in all_values[1:]:  # 헤더 제외
                if len(row) >= 3:
                    symbol, name, stock_type = row[0], row[1], row[2]
                    stocks[symbol] = {
                        'name': name,
                        'type': stock_type
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
                            info['stats'] = stats
                            info['df'] = df
                    except Exception as e:
                        st.warning(f"{symbol} 데이터 로드 실패: {e}")
                
                progress_bar.empty()
                status_text.empty()
                
                # 세션 상태 완전히 초기화 후 새 데이터로 설정
                st.session_state.monitoring_stocks.clear()
                st.session_state.monitoring_stocks.update(stocks)
                st.session_state.stocks_loaded = True
                
                # 캐시 무효화를 위해 강제로 새로고침
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

# 로컬 파일 저장/불러오기 함수 제거 - Google Sheets만 사용

class StockAnalyzer:
    def __init__(self):
        pass
    
    def search_korean_stock(self, query):
        """한국 주식 검색"""
        try:
            # 6자리 숫자면 종목코드로 검색
            if query.isdigit() and len(query) == 6:
                name = stock.get_market_ticker_name(query)
                if name:
                    return query, name
            
            # 종목명으로 검색 - NAVER, 삼성전자 등
            tickers = stock.get_market_ticker_list()
            query_upper = query.upper()
            

            
            # 전체 검색
            for ticker in tickers:
                try:
                    name = stock.get_market_ticker_name(ticker)
                    if name and query_upper in name.upper():
                        return ticker, name
                except Exception:
                    continue  # 개별 종목 오류는 무시하고 계속 진행
            
            return None, None
        except Exception as e:
            return None, None
    
    def get_stock_data(self, symbol, stock_type='KR'):
        """주식 데이터 가져오기"""
        try:
            if stock_type == 'KR':
                # 한국 주식
                df = stock.get_market_ohlcv_by_date(
                    fromdate=(datetime.now() - timedelta(days=365*5)).strftime('%Y%m%d'),
                    todate=datetime.now().strftime('%Y%m%d'),
                    ticker=symbol
                )
                
                # 빈 DataFrame 체크
                if df is None or df.empty:
                    st.warning(f"종목코드 {symbol}에 대한 데이터가 없습니다.")
                    return None
                
                # 컬럼명 확인 후 변경
                if len(df.columns) == 6:
                    # 시가, 고가, 저가, 종가, 거래량, 거래대금
                    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume', 'Value']
                    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                elif len(df.columns) == 5:
                    # 시가, 고가, 저가, 종가, 거래량
                    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                else:
                    # 기본 컬럼명 사용
                    pass
                
                # 데이터가 충분한지 확인
                if len(df) < 10:
                    st.warning(f"종목코드 {symbol}의 데이터가 부족합니다.")
                    return None
                
                df['Returns'] = df['Close'].pct_change() * 100
                
            else:
                # 미국 주식
                ticker = yf.Ticker(symbol)
                df = ticker.history(period='5y')
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
            # 빈 DataFrame 체크
            if df is None or df.empty:
                return None
            
            returns = df['Returns'].dropna()
            
            # 충분한 데이터가 있는지 확인
            if len(returns) < 10:
                return None
            
            # 기본 통계
            mean = returns.mean()
            std = returns.std()
            
            # 시그마 레벨
            sigma_1 = mean - std
            sigma_2 = mean - 2 * std
            sigma_3 = mean - 3 * std
            
            # 최근 종가 (안전하게)
            if len(df) > 0:
                last_close = df['Close'].iloc[-1]
            else:
                return None
            
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
                'last_close': last_close,
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
                price = stock.get_market_ohlcv_by_date(
                    fromdate=datetime.now().strftime('%Y%m%d'),
                    todate=datetime.now().strftime('%Y%m%d'),
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
                    change = ((current - previous) / previous) * 100
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
    if st.button("📂 Spreadsheets에서 불러오기", use_container_width=True, type="primary"):
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
                
                if stats:
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
                    st.metric("전일 종가", f"₩{analysis['stats']['last_close']:,.0f}")
                    st.caption("현재가 정보를 가져올 수 없습니다")
                else:
                    st.metric("전일 종가", f"${analysis['stats']['last_close']:,.2f}")
                    st.caption("현재가 정보를 가져올 수 없습니다")
        with col_b:
            st.metric("평균 수익률", f"{analysis['stats']['mean']:.2f}%")
        with col_c:
            st.metric("표준편차", f"{analysis['stats']['std']:.2f}%")
        with col_d:
            # 현재 변화율과 시그마 레벨 비교
            if current_price:
                change_pct = ((current_price - analysis['stats']['last_close']) / analysis['stats']['last_close']) * 100
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
        st.subheader("💰 시그마 하락시 목표 가격(어제 종가 기준)")
        
        # 어제 종가
        yesterday_close = analysis['stats']['last_close']
        
        # 1년 시그마 값들
        sigma_1_1y = analysis['stats'].get('1sigma_1y', analysis['stats']['1sigma'])
        sigma_2_1y = analysis['stats'].get('2sigma_1y', analysis['stats']['2sigma'])
        sigma_3_1y = analysis['stats'].get('3sigma_1y', analysis['stats']['3sigma'])
        
        # 시그마 하락시 가격 계산
        price_at_1sigma = yesterday_close * (1 + sigma_1_1y / 100)
        price_at_2sigma = yesterday_close * (1 + sigma_2_1y / 100)
        price_at_3sigma = yesterday_close * (1 + sigma_3_1y / 100)
        
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
        
        # 어제 종가 정보
        st.caption(f"* 어제 종가 기준: {currency}{price_format.format(yesterday_close)}")
        
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
                sigma_1_1y = analysis['stats'].get('1sigma_1y', sigma_1_5y)
                sigma_2_1y = analysis['stats'].get('2sigma_1y', sigma_2_5y)
                sigma_3_1y = analysis['stats'].get('3sigma_1y', sigma_3_5y)
                
                actual_prob_1_1y = (np.array(returns_1y) <= sigma_1_1y).sum() / len(returns_1y) * 100
                actual_prob_2_1y = (np.array(returns_1y) <= sigma_2_1y).sum() / len(returns_1y) * 100
                actual_prob_3_1y = (np.array(returns_1y) <= sigma_3_1y).sum() / len(returns_1y) * 100
            else:
                actual_prob_1_1y, actual_prob_2_1y, actual_prob_3_1y = actual_prob_1_5y, actual_prob_2_5y, actual_prob_3_5y
                sigma_1_1y, sigma_2_1y, sigma_3_1y = sigma_1_5y, sigma_2_5y, sigma_3_5y
            
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
                        # 어제 종가
                        yesterday_close = info['stats']['last_close']
                        
                        # 1년 시그마 값들 (퍼센트)
                        sigma_1_1y = info['stats'].get('1sigma_1y', info['stats']['1sigma'])
                        sigma_2_1y = info['stats'].get('2sigma_1y', info['stats']['2sigma'])
                        sigma_3_1y = info['stats'].get('3sigma_1y', info['stats']['3sigma'])
                        
                        # 시그마 하락시 가격 계산
                        price_at_1sigma = yesterday_close * (1 + sigma_1_1y / 100)
                        price_at_2sigma = yesterday_close * (1 + sigma_2_1y / 100)
                        price_at_3sigma = yesterday_close * (1 + sigma_3_1y / 100)
                        
                        current_prices_kr.append({
                            '종목': f"{info['name']} ({symbol})",
                            '어제 종가': f"₩{yesterday_close:,.0f}",
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
                        # 어제 종가
                        yesterday_close = info['stats']['last_close']
                        
                        # 1년 시그마 값들 (퍼센트)
                        sigma_1_1y = info['stats'].get('1sigma_1y', info['stats']['1sigma'])
                        sigma_2_1y = info['stats'].get('2sigma_1y', info['stats']['2sigma'])
                        sigma_3_1y = info['stats'].get('3sigma_1y', info['stats']['3sigma'])
                        
                        # 시그마 하락시 가격 계산
                        price_at_1sigma = yesterday_close * (1 + sigma_1_1y / 100)
                        price_at_2sigma = yesterday_close * (1 + sigma_2_1y / 100)
                        price_at_3sigma = yesterday_close * (1 + sigma_3_1y / 100)
                        
                        current_prices_us.append({
                            '종목': f"{info['name']} ({symbol})",
                            '어제 종가': f"${yesterday_close:,.2f}",
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
    
    # 투자 금액 설정 (라디오 버튼 제거)
    st.markdown("**투자 금액 설정**")
    col1_1, col1_2, col1_3 = st.columns(3)
    
    with col1_1:
        amount_1sigma = st.number_input("1σ 하락시", min_value=0, value=100)
    with col1_2:
        amount_2sigma = st.number_input("2σ 하락시", min_value=0, value=200)
    with col1_3:
        amount_3sigma = st.number_input("3σ 하락시", min_value=0, value=200)
    
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
            
            # 1년과 5년 데이터 모두 준비
            df_1year = df.tail(252)  # 1년 데이터
            df_5year = df  # 5년 데이터
            
            # 시그마 레벨 가져오기
            stats = analysis['stats']
            sigma_1 = stats['1sigma']
            sigma_2 = stats['2sigma']
            sigma_3 = stats['3sigma']
            
            # 백테스팅 함수 정의 (전략 파라미터 추가)
            def run_backtest(df_data, period_name, include_1sigma=True):
                buy_history = []
                total_investment = 0
                total_shares = 0
                
                for i in range(1, len(df_data)):
                    current_return = df_data['Returns'].iloc[i]
                    current_price = df_data['Close'].iloc[i]
                    current_date = df_data.index[i]
                    
                    # 3σ 하락 시
                    if current_return <= sigma_3:
                        if is_us_stock:
                            investment = amount_3sigma
                        else:
                            investment = amount_3sigma * 10000
                        shares = investment / current_price
                        buy_history.append({
                            'date': current_date,
                            'price': current_price,
                            'return': current_return,
                            'sigma_level': '3σ',
                            'investment': investment,
                            'shares': shares
                        })
                        total_investment += investment
                        total_shares += shares
                    
                    # 2σ 하락 시
                    elif current_return <= sigma_2:
                        if is_us_stock:
                            investment = amount_2sigma
                        else:
                            investment = amount_2sigma * 10000
                        shares = investment / current_price
                        buy_history.append({
                            'date': current_date,
                            'price': current_price,
                            'return': current_return,
                            'sigma_level': '2σ',
                            'investment': investment,
                            'shares': shares
                        })
                        total_investment += investment
                        total_shares += shares
                    
                    # 1σ 하락 시 (include_1sigma가 True일 때만)
                    elif include_1sigma and current_return <= sigma_1:
                        if is_us_stock:
                            investment = amount_1sigma
                        else:
                            investment = amount_1sigma * 10000
                        shares = investment / current_price
                        buy_history.append({
                            'date': current_date,
                            'price': current_price,
                            'return': current_return,
                            'sigma_level': '1σ',
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
            
            # DCA vs 일시불 비교 함수 (고정 금액 100만원 기준)
            def run_dca_vs_lump_sum_comparison(df_data, period_months):
                # 고정 투자금 설정 (100만원 또는 $1000)
                if is_us_stock:
                    fixed_investment = 1000  # $1000
                else:
                    fixed_investment = 1000000  # 100만원
                
                # DCA 투자 (매월 10일 종가)
                dca_investment = 0
                dca_shares = 0
                dca_buy_count = 0
                dca_buy_history = []
                monthly_amount = fixed_investment / period_months
                
                # 일시불 투자 (시작 시점의 10일 또는 그 이후 첫 거래일)
                lump_sum_price = None
                lump_sum_date = None
                
                # 시작월의 10일 이후 첫 거래일 찾기
                start_year = df_data.index[0].year
                start_month = df_data.index[0].month
                
                for i in range(len(df_data)):
                    current_date = df_data.index[i]
                    if (current_date.year == start_year and 
                        current_date.month == start_month and 
                        current_date.day >= 10):
                        lump_sum_price = df_data['Close'].iloc[i]
                        lump_sum_date = current_date
                        break
                
                # 10일 이후 거래일이 없으면 다음 달 첫 거래일
                if lump_sum_price is None:
                    for i in range(len(df_data)):
                        current_date = df_data.index[i]
                        if current_date.year > start_year or current_date.month > start_month:
                            lump_sum_price = df_data['Close'].iloc[i]
                            lump_sum_date = current_date
                            break
                
                # 그래도 없으면 첫 거래일
                if lump_sum_price is None:
                    lump_sum_price = df_data['Close'].iloc[0]
                    lump_sum_date = df_data.index[0]
                
                lump_sum_shares = fixed_investment / lump_sum_price
                lump_sum_investment = fixed_investment
                
                # DCA: 매월 10일 찾기 (정확히 12개월 또는 60개월)
                target_months = period_months
                found_months = 0
                last_month = -1
                last_year = -1
                
                for i in range(len(df_data)):
                    current_date = df_data.index[i]
                    current_month = current_date.month
                    current_year = current_date.year
                    
                    # 매월 10일 또는 10일 이후 첫 거래일
                    if (current_date.day >= 10 and 
                        (current_year != last_year or current_month != last_month) and 
                        found_months < target_months):
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
                        last_month = current_month
                        last_year = current_year
                
                # 현재 가격
                current_price = df_data['Close'].iloc[-1]
                
                # DCA 결과
                dca_current_value = dca_shares * current_price
                dca_total_return = ((dca_current_value - dca_investment) / dca_investment) * 100 if dca_investment > 0 else 0
                dca_avg_price = dca_investment / dca_shares if dca_shares > 0 else 0
                
                # 일시불 결과
                lump_sum_current_value = lump_sum_shares * current_price
                lump_sum_total_return = ((lump_sum_current_value - lump_sum_investment) / lump_sum_investment) * 100 if lump_sum_investment > 0 else 0
                lump_sum_avg_price = lump_sum_investment / lump_sum_shares if lump_sum_shares > 0 else 0
                
                return {
                    'dca': {
                        'buy_count': dca_buy_count,
                        'total_investment': fixed_investment,
                        'monthly_amount': monthly_amount,
                        'avg_price': dca_avg_price,
                        'total_shares': dca_shares,
                        'current_value': dca_current_value,
                        'total_return': dca_total_return,
                        'buy_history': dca_buy_history
                    },
                    'lump_sum': {
                        'buy_count': 1,
                        'total_investment': lump_sum_investment,
                        'avg_price': lump_sum_avg_price,
                        'total_shares': lump_sum_shares,
                        'current_value': lump_sum_current_value,
                        'total_return': lump_sum_total_return,
                        'buy_date': lump_sum_date
                    }
                }
            
            # 미국 주식인지 확인
            is_us_stock = analysis['type'] == 'US'
            
            # 백테스팅 실행
            with st.spinner("백테스팅 분석 중..."):
                # 1σ 전략 백테스팅
                results_1sigma_1year = run_backtest(df_1year, "1년", include_1sigma=True)
                results_1sigma_5year = run_backtest(df_5year, "5년", include_1sigma=True)
                
                # 2σ 전략 백테스팅 (1σ 제외)
                results_2sigma_1year = run_backtest(df_1year, "1년", include_1sigma=False)
                results_2sigma_5year = run_backtest(df_5year, "5년", include_1sigma=False)
                
                # DCA vs 일시불 계산 (고정 100만원 또는 $1000)
                comparison_1y = run_dca_vs_lump_sum_comparison(df_1year, 12)
                comparison_5y = run_dca_vs_lump_sum_comparison(df_5year, 60)
            
            # 결과 표시
            st.success("✅ 백테스팅 완료!")
            
            # 4가지 전략 비교 섹션
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
                    # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
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
                    
                    # 둘째 행: 총 투자금, 수익률
                    col4, col5 = st.columns(2)
                    with col4:
                        if is_us_stock:
                            st.metric("총 투자금", f"${results_2sigma_1year['total_investment']:,.0f}")
                        else:
                            st.metric("총 투자금", f"₩{results_2sigma_1year['total_investment']:,.0f}")
                    with col5:
                        st.metric("수익률", f"{results_2sigma_1year['total_return']:+.2f}%",
                                 delta=f"{results_2sigma_1year['total_return']:+.2f}%")
                    
                    # 매수 내역
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
                    # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
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
                    
                    # 둘째 행: 총 투자금, 수익률
                    col4, col5 = st.columns(2)
                    with col4:
                        if is_us_stock:
                            st.metric("총 투자금", f"${results_2sigma_5year['total_investment']:,.0f}")
                        else:
                            st.metric("총 투자금", f"₩{results_2sigma_5year['total_investment']:,.0f}")
                    with col5:
                        st.metric("수익률", f"{results_2sigma_5year['total_return']:+.2f}%",
                                 delta=f"{results_2sigma_5year['total_return']:+.2f}%")
                    
                    # 매수 내역
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
            st.caption(f"고정 투자금: {'$1,000' if is_us_stock else '100만원'}")
            
            col_dca_1y, col_dca_5y = st.columns(2)
            
            with col_dca_1y:
                st.markdown("**📅 최근 1년**")
                if comparison_1y['dca']['buy_count'] > 0:
                    # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("매수 횟수", f"{comparison_1y['dca']['buy_count']}회")
                    with col2:
                        if is_us_stock:
                            st.metric("평균 매수 단가", f"${comparison_1y['dca']['avg_price']:,.2f}")
                        else:
                            st.metric("평균 매수 단가", f"₩{comparison_1y['dca']['avg_price']:,.0f}")
                    with col3:
                        st.metric("보유 주식수", f"{comparison_1y['dca']['total_shares']:.2f}주")
                    
                    # 둘째 행: 총 투자금, 수익률
                    col4, col5 = st.columns(2)
                    with col4:
                        if is_us_stock:
                            st.metric("총 투자금", f"${comparison_1y['dca']['total_investment']:,.0f}")
                        else:
                            st.metric("총 투자금", f"₩{comparison_1y['dca']['total_investment']:,.0f}")
                    with col5:
                        st.metric("수익률", f"{comparison_1y['dca']['total_return']:+.2f}%",
                                 delta=f"{comparison_1y['dca']['total_return']:+.2f}%")
                    
                    # 매수 내역
                    with st.expander(f"📋 매수 내역 ({comparison_1y['dca']['buy_count']}건)"):
                        if comparison_1y['dca']['buy_history']:
                            dca_df = pd.DataFrame(comparison_1y['dca']['buy_history'])
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
                if comparison_5y['dca']['buy_count'] > 0:
                    # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("매수 횟수", f"{comparison_5y['dca']['buy_count']}회")
                    with col2:
                        if is_us_stock:
                            st.metric("평균 매수 단가", f"${comparison_5y['dca']['avg_price']:,.2f}")
                        else:
                            st.metric("평균 매수 단가", f"₩{comparison_5y['dca']['avg_price']:,.0f}")
                    with col3:
                        st.metric("보유 주식수", f"{comparison_5y['dca']['total_shares']:.2f}주")
                    
                    # 둘째 행: 총 투자금, 수익률
                    col4, col5 = st.columns(2)
                    with col4:
                        if is_us_stock:
                            st.metric("총 투자금", f"${comparison_5y['dca']['total_investment']:,.0f}")
                        else:
                            st.metric("총 투자금", f"₩{comparison_5y['dca']['total_investment']:,.0f}")
                    with col5:
                        st.metric("수익률", f"{comparison_5y['dca']['total_return']:+.2f}%",
                                 delta=f"{comparison_5y['dca']['total_return']:+.2f}%")
                    
                    # 매수 내역
                    with st.expander(f"📋 매수 내역 ({comparison_5y['dca']['buy_count']}건)"):
                        if comparison_5y['dca']['buy_history']:
                            dca_df = pd.DataFrame(comparison_5y['dca']['buy_history'])
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
            
            # 일시불 전략
            st.markdown("---")
            st.markdown("### 4️⃣ 일시불 투자")
            st.caption(f"고정 투자금: {'$1,000' if is_us_stock else '100만원'}")
            
            col_lump_1y, col_lump_5y = st.columns(2)
            
            with col_lump_1y:
                st.markdown("**📅 최근 1년**")
                if comparison_1y['lump_sum']['buy_count'] > 0:
                    # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("매수 횟수", f"{comparison_1y['lump_sum']['buy_count']}회")
                    with col2:
                        if is_us_stock:
                            st.metric("평균 매수 단가", f"${comparison_1y['lump_sum']['avg_price']:,.2f}")
                        else:
                            st.metric("평균 매수 단가", f"₩{comparison_1y['lump_sum']['avg_price']:,.0f}")
                    with col3:
                        st.metric("보유 주식수", f"{comparison_1y['lump_sum']['total_shares']:.2f}주")
                    
                    # 둘째 행: 총 투자금, 수익률
                    col4, col5 = st.columns(2)
                    with col4:
                        if is_us_stock:
                            st.metric("총 투자금", f"${comparison_1y['lump_sum']['total_investment']:,.0f}")
                        else:
                            st.metric("총 투자금", f"₩{comparison_1y['lump_sum']['total_investment']:,.0f}")
                    with col5:
                        st.metric("수익률", f"{comparison_1y['lump_sum']['total_return']:+.2f}%",
                                 delta=f"{comparison_1y['lump_sum']['total_return']:+.2f}%")
                    
                    # 매수 날짜 표시
                    if 'buy_date' in comparison_1y['lump_sum']:
                        st.info(f"📅 매수일: {comparison_1y['lump_sum']['buy_date'].strftime('%Y.%m.%d')}")
                else:
                    st.info("매수 내역 없음")
            
            with col_lump_5y:
                st.markdown("**📅 최근 5년**")
                if comparison_5y['lump_sum']['buy_count'] > 0:
                    # 첫 행: 매수횟수, 평균 매수 단가, 보유주식수
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("매수 횟수", f"{comparison_5y['lump_sum']['buy_count']}회")
                    with col2:
                        if is_us_stock:
                            st.metric("평균 매수 단가", f"${comparison_5y['lump_sum']['avg_price']:,.2f}")
                        else:
                            st.metric("평균 매수 단가", f"₩{comparison_5y['lump_sum']['avg_price']:,.0f}")
                    with col3:
                        st.metric("보유 주식수", f"{comparison_5y['lump_sum']['total_shares']:.2f}주")
                    
                    # 둘째 행: 총 투자금, 수익률
                    col4, col5 = st.columns(2)
                    with col4:
                        if is_us_stock:
                            st.metric("총 투자금", f"${comparison_5y['lump_sum']['total_investment']:,.0f}")
                        else:
                            st.metric("총 투자금", f"₩{comparison_5y['lump_sum']['total_investment']:,.0f}")
                    with col5:
                        st.metric("수익률", f"{comparison_5y['lump_sum']['total_return']:+.2f}%",
                                 delta=f"{comparison_5y['lump_sum']['total_return']:+.2f}%")
                    
                    # 매수 날짜 표시
                    if 'buy_date' in comparison_5y['lump_sum']:
                        st.info(f"📅 매수일: {comparison_5y['lump_sum']['buy_date'].strftime('%Y.%m.%d')}")
                else:
                    st.info("매수 내역 없음")
            
            # 수익률 비교 그래프 (투자 효율 기준)
            st.markdown("---")
            st.markdown("#### 📊 투자 효율 비교 (100만원당 수익률)")
            
            col_graph_1y, col_graph_5y = st.columns(2)
            
            # 1년 결과 그래프
            with col_graph_1y:
                st.markdown("**1년 투자 효율 비교**")
                
                # 1년 투자 효율 계산 (100만원당 수익률)
                efficiency_1y = []
                labels_1y = []
                
                # 1σ 전략 효율
                if results_1sigma_1year['total_investment'] > 0:
                    efficiency_1sigma = results_1sigma_1year['total_return']
                else:
                    efficiency_1sigma = 0
                efficiency_1y.append(efficiency_1sigma)
                labels_1y.append('1σ 전략')
                
                # 2σ 전략 효율
                if results_2sigma_1year['total_investment'] > 0:
                    efficiency_2sigma = results_2sigma_1year['total_return']
                else:
                    efficiency_2sigma = 0
                efficiency_1y.append(efficiency_2sigma)
                labels_1y.append('2σ 전략')
                
                # DCA와 일시불은 이미 100만원 기준
                efficiency_1y.append(comparison_1y['dca']['total_return'])
                labels_1y.append('DCA')
                efficiency_1y.append(comparison_1y['lump_sum']['total_return'])
                labels_1y.append('일시불')
                
                # 1년 그래프
                fig_1y = go.Figure()
                fig_1y.add_trace(go.Bar(
                    x=labels_1y,
                    y=efficiency_1y,
                    text=[f'{e:+.2f}%' for e in efficiency_1y],
                    textposition='auto',
                    marker_color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
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
                
                # 5년 투자 효율 계산
                efficiency_5y = []
                labels_5y = []
                
                # 1σ 전략 효율
                if results_1sigma_5year['total_investment'] > 0:
                    efficiency_1sigma_5y = results_1sigma_5year['total_return']
                else:
                    efficiency_1sigma_5y = 0
                efficiency_5y.append(efficiency_1sigma_5y)
                labels_5y.append('1σ 전략')
                
                # 2σ 전략 효율
                if results_2sigma_5year['total_investment'] > 0:
                    efficiency_2sigma_5y = results_2sigma_5year['total_return']
                else:
                    efficiency_2sigma_5y = 0
                efficiency_5y.append(efficiency_2sigma_5y)
                labels_5y.append('2σ 전략')
                
                # DCA와 일시불
                efficiency_5y.append(comparison_5y['dca']['total_return'])
                labels_5y.append('DCA')
                efficiency_5y.append(comparison_5y['lump_sum']['total_return'])
                labels_5y.append('일시불')
                
                # 5년 그래프
                fig_5y = go.Figure()
                fig_5y.add_trace(go.Bar(
                    x=labels_5y,
                    y=efficiency_5y,
                    text=[f'{e:+.2f}%' for e in efficiency_5y],
                    textposition='auto',
                    marker_color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
                ))
                fig_5y.update_layout(
                    title="5년 투자 효율",
                    xaxis_title="투자 전략",
                    yaxis_title="수익률 (%)",
                    height=400,
                    showlegend=False
                )
                st.plotly_chart(fig_5y, use_container_width=True)
            
            # 설명 추가
            with st.expander("📌 투자 효율 설명"):
                st.caption(f"""
                - **1σ/2σ 전략**: 실제 투자 금액 대비 수익률
                - **DCA/일시불**: {'$1,000' if is_us_stock else '100만원'} 고정 투자 기준 수익률
                - 모든 전략을 동일한 기준으로 비교하기 위한 효율성 지표입니다.
                """)

            import numpy as np
            
            # 종합 분석 보고서 섹션
            st.markdown("---")
            st.markdown("## 📊 백테스팅 종합 분석 보고서")
            
            # 1. 핵심 성과 요약
            st.markdown("### 1. 핵심 성과 요약")
            
            # 수익률 순위 계산
            strategies_1y = [
                ("1σ 전략", results_1sigma_1year['total_return']),
                ("2σ 전략", results_2sigma_1year['total_return']),
                ("DCA", comparison_1y['dca']['total_return']),
                ("일시불", comparison_1y['lump_sum']['total_return'])
            ]
            strategies_5y = [
                ("1σ 전략", results_1sigma_5year['total_return']),
                ("2σ 전략", results_2sigma_5year['total_return']),
                ("DCA", comparison_5y['dca']['total_return']),
                ("일시불", comparison_5y['lump_sum']['total_return'])
            ]
            
            # 정렬
            strategies_1y_sorted = sorted(strategies_1y, key=lambda x: x[1], reverse=True)
            strategies_5y_sorted = sorted(strategies_5y, key=lambda x: x[1], reverse=True)
            
            # 랭킹 테이블
            col_rank_1y, col_rank_5y = st.columns(2)
            
            with col_rank_1y:
                st.markdown("**📈 1년 수익률 랭킹**")
                rank_emojis = ["🥇", "🥈", "🥉", "4️⃣"]
                for i, (name, return_rate) in enumerate(strategies_1y_sorted):
                    st.write(f"{rank_emojis[i]} {name}: **{return_rate:+.2f}%**")
            
            with col_rank_5y:
                st.markdown("**📈 5년 수익률 랭킹**")
                for i, (name, return_rate) in enumerate(strategies_5y_sorted):
                    st.write(f"{rank_emojis[i]} {name}: **{return_rate:+.2f}%**")
            
            # 2. 전략별 특성 분석 (데이터 기반)
            st.markdown("---")
            st.markdown("### 2. 전략별 특성 분석")
            
            # 실제 데이터 기반 분석
            strategies_data = [
                {
                    "name": "**1σ 하락시 매수 전략**",
                    "buy_count_1y": results_1sigma_1year['buy_count'],
                    "buy_count_5y": results_1sigma_5year['buy_count'],
                    "total_inv_1y": results_1sigma_1year['total_investment'],
                    "total_inv_5y": results_1sigma_5year['total_investment'],
                    "return_1y": results_1sigma_1year['total_return'],
                    "return_5y": results_1sigma_5year['total_return']
                },
                {
                    "name": "**2σ 하락시 매수 전략**",
                    "buy_count_1y": results_2sigma_1year['buy_count'],
                    "buy_count_5y": results_2sigma_5year['buy_count'],
                    "total_inv_1y": results_2sigma_1year['total_investment'],
                    "total_inv_5y": results_2sigma_5year['total_investment'],
                    "return_1y": results_2sigma_1year['total_return'],
                    "return_5y": results_2sigma_5year['total_return']
                },
                {
                    "name": "**DCA (매월 정액 투자)**",
                    "buy_count_1y": comparison_1y['dca']['buy_count'],
                    "buy_count_5y": comparison_5y['dca']['buy_count'],
                    "total_inv_1y": comparison_1y['dca']['total_investment'],
                    "total_inv_5y": comparison_5y['dca']['total_investment'],
                    "return_1y": comparison_1y['dca']['total_return'],
                    "return_5y": comparison_5y['dca']['total_return']
                },
                {
                    "name": "**일시불 투자**",
                    "buy_count_1y": comparison_1y['lump_sum']['buy_count'],
                    "buy_count_5y": comparison_5y['lump_sum']['buy_count'],
                    "total_inv_1y": comparison_1y['lump_sum']['total_investment'],
                    "total_inv_5y": comparison_5y['lump_sum']['total_investment'],
                    "return_1y": comparison_1y['lump_sum']['total_return'],
                    "return_5y": comparison_5y['lump_sum']['total_return']
                }
            ]
            
            for strategy in strategies_data:
                with st.expander(strategy["name"]):
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        st.markdown("**1년 데이터**")
                        st.write(f"• 매수 횟수: {strategy['buy_count_1y']}회")
                        if is_us_stock:
                            st.write(f"• 총 투자금: ${strategy['total_inv_1y']:,.0f}")
                        else:
                            st.write(f"• 총 투자금: ₩{strategy['total_inv_1y']:,.0f}")
                        st.write(f"• 수익률: {strategy['return_1y']:+.2f}%")
                        
                        # 효율성 지표
                        if strategy['buy_count_1y'] > 0:
                            efficiency = strategy['return_1y'] / strategy['buy_count_1y']
                            st.write(f"• 매수당 평균 수익률: {efficiency:+.2f}%")
                    
                    with col_s2:
                        st.markdown("**5년 데이터**")
                        st.write(f"• 매수 횟수: {strategy['buy_count_5y']}회")
                        if is_us_stock:
                            st.write(f"• 총 투자금: ${strategy['total_inv_5y']:,.0f}")
                        else:
                            st.write(f"• 총 투자금: ₩{strategy['total_inv_5y']:,.0f}")
                        st.write(f"• 수익률: {strategy['return_5y']:+.2f}%")
                        
                        if strategy['buy_count_5y'] > 0:
                            efficiency = strategy['return_5y'] / strategy['buy_count_5y']
                            st.write(f"• 매수당 평균 수익률: {efficiency:+.2f}%")
            
            # 3. 시장 환경 분석
            st.markdown("---")
            st.markdown("### 3. 시장 환경 분석")
           
            # 현재 가격 및 이동평균 계산
            current_price = analysis['df']['Close'].iloc[-1]
            ma_20 = analysis['df']['Close'].tail(20).mean()
            ma_60 = analysis['df']['Close'].tail(60).mean()
            ma_200 = analysis['df']['Close'].tail(200).mean() if len(analysis['df']) >= 200 else None
           
            year_high = analysis['df']['Close'].tail(252).max() if len(analysis['df']) >= 252 else analysis['df']['Close'].max()
            year_low = analysis['df']['Close'].tail(252).min() if len(analysis['df']) >= 252 else analysis['df']['Close'].min()
            all_time_high = analysis['df']['Close'].max()
            
            st.markdown("**📍 현재 위치 평가**")
            
            col_pos1, col_pos2, col_pos3 = st.columns(3)
            
            with col_pos1:
                st.metric("52주 최고가 대비", 
                            f"{((current_price - year_high) / year_high * 100):+.1f}%")
                st.metric("52주 최저가 대비", 
                            f"{((current_price - year_low) / year_low * 100):+.1f}%")
            
            with col_pos2:
                st.metric("역사적 고점 대비", 
                            f"{((current_price - all_time_high) / all_time_high * 100):+.1f}%")
                st.metric("20일 이동평균 대비", 
                            f"{((current_price - ma_20) / ma_20 * 100):+.1f}%")
            
            with col_pos3:
                st.metric("60일 이동평균 대비", 
                            f"{((current_price - ma_60) / ma_60 * 100):+.1f}%")
                if ma_200:
                    st.metric("200일 이동평균 대비", 
                                f"{((current_price - ma_200) / ma_200 * 100):+.1f}%")
            
            # 4. 변동성 분석
            st.markdown("---")
            st.markdown("### 4. 변동성 분석")
            
            # 변동성 계산
            daily_returns = analysis['df']['Close'].pct_change()
            daily_volatility = daily_returns.std()
            annual_volatility = daily_volatility * np.sqrt(252) * 100
            
            # 최근 60일 vs 전체 기간 변동성 비교
            recent_volatility = daily_returns.tail(60).std() * np.sqrt(252) * 100
            
            col_vol1, col_vol2, col_vol3 = st.columns(3)
            
            with col_vol1:
                st.metric("연간 변동성", f"{annual_volatility:.1f}%")
            
            with col_vol2:
                st.metric("최근 60일 변동성", f"{recent_volatility:.1f}%")
            
            with col_vol3:
                vol_change = ((recent_volatility - annual_volatility) / annual_volatility) * 100
                st.metric("변동성 변화", f"{vol_change:+.1f}%")
            
            # 변동성 상태 판단
            if recent_volatility > annual_volatility * 1.2:
                vol_state = "⚠️ 변동성 확대 구간"
            elif recent_volatility < annual_volatility * 0.8:
                vol_state = "😴 변동성 축소 구간"
            else:
                vol_state = "👌 정상 변동성 구간"
            
            st.info(f"현재 시장 상태: **{vol_state}**")
            
            # 5. 전략 효율성 비교
            st.markdown("---")
            st.markdown("### 5. 전략 효율성 비교")
            
            # 투자 대비 수익률 (ROI) 계산
            efficiency_data = []
            
            # 1σ 전략
            if results_1sigma_5year['total_investment'] > 0:
                roi_1sigma = (results_1sigma_5year['current_value'] - results_1sigma_5year['total_investment']) / results_1sigma_5year['total_investment'] * 100
                efficiency_data.append(("1σ 전략", roi_1sigma, results_1sigma_5year['buy_count']))
            
            # 2σ 전략
            if results_2sigma_5year['total_investment'] > 0:
                roi_2sigma = (results_2sigma_5year['current_value'] - results_2sigma_5year['total_investment']) / results_2sigma_5year['total_investment'] * 100
                efficiency_data.append(("2σ 전략", roi_2sigma, results_2sigma_5year['buy_count']))
            
            # DCA
            roi_dca = comparison_5y['dca']['total_return']
            efficiency_data.append(("DCA", roi_dca, comparison_5y['dca']['buy_count']))
            
            # 일시불
            roi_lump = comparison_5y['lump_sum']['total_return']
            efficiency_data.append(("일시불", roi_lump, comparison_5y['lump_sum']['buy_count']))
            
            # 효율성 테이블
            efficiency_df = pd.DataFrame(efficiency_data, columns=['전략', '5년 ROI (%)', '거래 횟수'])
            efficiency_df['거래당 효율'] = efficiency_df['5년 ROI (%)'] / efficiency_df['거래 횟수']
            efficiency_df = efficiency_df.sort_values('5년 ROI (%)', ascending=False)
            
            st.dataframe(efficiency_df.style.format({
                '5년 ROI (%)': '{:+.2f}%',
                '거래 횟수': '{:.0f}회',
                '거래당 효율': '{:+.2f}'
            }), use_container_width=True, hide_index=True)
            
            # 6. 최종 요약
            st.markdown("---")
            st.markdown("### 6. 최종 요약")
            
            # 최고 전략 선정
            best_1y = strategies_1y_sorted[0][0]
            best_5y = strategies_5y_sorted[0][0]
            
            # 실제 데이터 기반 요약
            summary_points = []
            
            # 1년 vs 5년 최고 전략
            if best_1y == best_5y:
                summary_points.append(f"✅ {best_1y}이 단기/장기 모두 최고 성과")
            else:
                summary_points.append(f"✅ 단기(1년): {best_1y} 최고")
                summary_points.append(f"✅ 장기(5년): {best_5y} 최고")
            
            # 거래 빈도 비교
            if results_1sigma_5year['buy_count'] > 0:
                summary_points.append(f"✅ 1σ 전략: 5년간 {results_1sigma_5year['buy_count']}회 매수 (가장 활발)")
            if results_2sigma_5year['buy_count'] > 0:
                summary_points.append(f"✅ 2σ 전략: 5년간 {results_2sigma_5year['buy_count']}회 매수 (선별적)")
            
            # 변동성 상태
            summary_points.append(f"✅ 현재 변동성: {recent_volatility:.1f}% (5년 평균 대비 {vol_change:+.1f}%)")
            
            st.info("\n\n".join(summary_points))
            
            st.warning("""
            ⚠️ **중요 고지사항**
            - 과거 성과는 미래 수익을 보장하지 않습니다
            - 백테스팅은 거래 비용과 슬리피지를 고려하지 않았습니다
            - 실제 투자 시 시장 상황과 개인 여건을 종합적으로 고려하세요
            """)
            
        else:
            st.info("백테스팅 실행 버튼을 클릭하여 분석을 시작하세요.")