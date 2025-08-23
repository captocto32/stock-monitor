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
    
    # 투자 금액 설정
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
            # [기존 백테스팅 코드 유지 - 1σ, 2σ, DCA 전략 실행]
            # ... (기존 코드)
            
            # 수익률 비교 그래프 (일시불 제외 버전)
            st.markdown("---")
            st.markdown("#### 📊 투자 효율 비교 (100만원당 수익률)")
            
            col_graph_1y, col_graph_5y = st.columns(2)
            
            # 1년 결과 그래프
            with col_graph_1y:
                st.markdown("**1년 투자 효율 비교**")
                
                efficiency_1y = []
                labels_1y = []
                
                # 1σ, 2σ, DCA만 포함
                if results_1sigma_1year['total_investment'] > 0:
                    efficiency_1y.append(results_1sigma_1year['total_return'])
                    labels_1y.append('1σ 전략')
                
                if results_2sigma_1year['total_investment'] > 0:
                    efficiency_1y.append(results_2sigma_1year['total_return'])
                    labels_1y.append('2σ 전략')
                
                efficiency_1y.append(comparison_1y['dca']['total_return'])
                labels_1y.append('DCA')
                
                # 1년 그래프
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
                    labels_5y.append('1σ 전략')
                
                if results_2sigma_5year['total_investment'] > 0:
                    efficiency_5y.append(results_2sigma_5year['total_return'])
                    labels_5y.append('2σ 전략')
                
                efficiency_5y.append(comparison_5y['dca']['total_return'])
                labels_5y.append('DCA')
                
                # 5년 그래프
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
            
            # ============= 몬테카를로 최적화 섹션 =============
            st.markdown("---")
            st.markdown("## 🎲 몬테카를로 최적화")
            
            # 몬테카를로 함수 정의
            def monte_carlo_optimization(df_data, sigma_stats, num_simulations=5000):
                """몬테카를로 시뮬레이션으로 최적 비중 찾기"""
                best_result = {
                    'sharpe': -999,
                    'weights': None,
                    'return': None,
                    'std': None,
                    'all_results': []
                }
                
                all_combinations = []
                
                for i in range(num_simulations):
                    # 무작위 비중 생성
                    weights = np.random.random(3)
                    weights = weights / weights.sum()  # 정규화
                    
                    # 각 전략의 실제 수익률 사용 (백테스팅 결과 활용)
                    # 5년 데이터 기준
                    portfolio_return = (
                        weights[0] * (results_1sigma_5year['total_return'] if results_1sigma_5year['total_investment'] > 0 else 0) +
                        weights[1] * (results_2sigma_5year['total_return'] if results_2sigma_5year['total_investment'] > 0 else 0) +
                        weights[2] * comparison_5y['dca']['total_return']
                    )
                    
                    # 간단한 리스크 추정 (각 전략의 변동성을 추정)
                    portfolio_std = np.sqrt(
                        (weights[0]**2 * 15**2) +  # 1σ 전략 추정 변동성
                        (weights[1]**2 * 12**2) +  # 2σ 전략 추정 변동성
                        (weights[2]**2 * 8**2)      # DCA 추정 변동성
                    )
                    
                    sharpe = portfolio_return / portfolio_std if portfolio_std > 0 else 0
                    
                    all_combinations.append({
                        'weights': weights.copy(),
                        'return': portfolio_return,
                        'std': portfolio_std,
                        'sharpe': sharpe
                    })
                    
                    if sharpe > best_result['sharpe']:
                        best_result = {
                            'sharpe': sharpe,
                            'weights': weights.copy(),
                            'return': portfolio_return,
                            'std': portfolio_std
                        }
                
                return best_result, all_combinations
            
            # 몬테카를로 실행 버튼
            col_mc1, col_mc2 = st.columns([3, 1])
            
            with col_mc1:
                st.info("""
                **몬테카를로 시뮬레이션이란?**
                - 5,000가지 전략 비중 조합을 무작위로 테스트
                - 리스크 대비 수익(샤프비율)이 가장 높은 조합 발견
                - 최적의 자산 배분 비율 제시
                """)
            
            with col_mc2:
                if st.button("🎯 최적 비중 찾기", type="secondary", use_container_width=True):
                    with st.spinner("5,000개 조합 분석 중..."):
                        # 프로그레스 바
                        progress_bar = st.progress(0)
                        
                        # 몬테카를로 실행
                        best_result, all_combinations = monte_carlo_optimization(
                            df_5year,
                            stats
                        )
                        
                        progress_bar.progress(100)
                        
                        # 결과 표시
                        st.success("✅ 최적 비중 발견!")
                        
                        # 최적 비중 표시
                        col_opt1, col_opt2, col_opt3 = st.columns(3)
                        
                        with col_opt1:
                            st.metric("1σ 전략", f"{best_result['weights'][0]:.1%}")
                        
                        with col_opt2:
                            st.metric("2σ 전략", f"{best_result['weights'][1]:.1%}")
                        
                        with col_opt3:
                            st.metric("DCA", f"{best_result['weights'][2]:.1%}")
                        
                        # 예상 성과
                        st.markdown("### 📊 최적 포트폴리오 예상 성과")
                        col_perf1, col_perf2, col_perf3 = st.columns(3)
                        
                        with col_perf1:
                            st.metric("예상 수익률", f"{best_result['return']:.1%}")
                        
                        with col_perf2:
                            st.metric("예상 변동성", f"{best_result['std']:.1%}")
                        
                        with col_perf3:
                            st.metric("샤프비율", f"{best_result['sharpe']:.2f}")
                        
                        # 효율적 프론티어 시각화
                        st.markdown("### 📈 리스크-수익 분석")
                        
                        # 모든 조합의 산점도
                        returns = [c['return'] for c in all_combinations]
                        stds = [c['std'] for c in all_combinations]
                        sharpes = [c['sharpe'] for c in all_combinations]
                        
                        fig_frontier = go.Figure()
                        
                        # 모든 조합
                        fig_frontier.add_trace(go.Scatter(
                            x=stds,
                            y=returns,
                            mode='markers',
                            marker=dict(
                                size=5,
                                color=sharpes,
                                colorscale='Viridis',
                                showscale=True,
                                colorbar=dict(title="샤프비율")
                            ),
                            text=[f"수익: {r:.1f}%<br>리스크: {s:.1f}%<br>샤프: {sh:.2f}" 
                                  for r, s, sh in zip(returns, stds, sharpes)],
                            hovertemplate='%{text}<extra></extra>',
                            name='모든 조합'
                        ))
                        
                        # 최적 포트폴리오 강조
                        fig_frontier.add_trace(go.Scatter(
                            x=[best_result['std']],
                            y=[best_result['return']],
                            mode='markers',
                            marker=dict(
                                size=15,
                                color='red',
                                symbol='star',
                                line=dict(color='darkred', width=2)
                            ),
                            name='최적 포트폴리오',
                            text=f"최적: 수익 {best_result['return']:.1f}%, 리스크 {best_result['std']:.1f}%",
                            hovertemplate='%{text}<extra></extra>'
                        ))
                        
                        # 개별 전략들도 표시
                        individual_strategies = [
                            ("1σ 전략", results_1sigma_5year['total_return'] if results_1sigma_5year['total_investment'] > 0 else 0, 15),
                            ("2σ 전략", results_2sigma_5year['total_return'] if results_2sigma_5year['total_investment'] > 0 else 0, 12),
                            ("DCA", comparison_5y['dca']['total_return'], 8)
                        ]
                        
                        for name, ret, std in individual_strategies:
                            fig_frontier.add_trace(go.Scatter(
                                x=[std],
                                y=[ret],
                                mode='markers+text',
                                marker=dict(size=10, symbol='diamond'),
                                text=[name],
                                textposition="top center",
                                name=name
                            ))
                        
                        fig_frontier.update_layout(
                            title="효율적 프론티어 (Efficient Frontier)",
                            xaxis_title="리스크 (표준편차 %)",
                            yaxis_title="수익률 (%)",
                            height=500,
                            hovermode='closest'
                        )
                        
                        st.plotly_chart(fig_frontier, use_container_width=True)
                        
                        # 저장할 수 있도록 세션 스테이트에 저장
                        st.session_state['optimal_weights'] = best_result['weights']
            
            # ============= 혼합 전략 백테스팅 =============
            st.markdown("---")
            st.markdown("## 🔄 혼합 전략 백테스팅")
            
            # 혼합 전략 설정
            st.markdown("### 전략 비중 설정")
            
            col_mix1, col_mix2 = st.columns([3, 1])
            
            with col_mix1:
                # 슬라이더로 비중 조절
                st.markdown("**각 전략의 비중을 조절하세요**")
                
                # 최적 비중이 있으면 기본값으로 사용
                if 'optimal_weights' in st.session_state:
                    default_weights = st.session_state['optimal_weights']
                else:
                    default_weights = [0.33, 0.33, 0.34]
                
                weight_1sigma = st.slider("1σ 전략 비중", 0.0, 1.0, float(default_weights[0]), 0.05)
                weight_2sigma = st.slider("2σ 전략 비중", 0.0, 1.0, float(default_weights[1]), 0.05)
                weight_dca = st.slider("DCA 비중", 0.0, 1.0, float(default_weights[2]), 0.05)
                
                # 합계 확인
                total_weight = weight_1sigma + weight_2sigma + weight_dca
                
                if abs(total_weight - 1.0) > 0.01:
                    st.warning(f"⚠️ 비중 합계: {total_weight:.1%} (100%가 되도록 조정해주세요)")
                else:
                    st.success(f"✅ 비중 합계: {total_weight:.1%}")
            
            with col_mix2:
                if 'optimal_weights' in st.session_state:
                    if st.button("🎯 최적 비중 적용", use_container_width=True):
                        st.rerun()
            
            # 혼합 전략 실행 버튼
            if st.button("🚀 혼합 전략 실행", type="primary", use_container_width=True):
                if abs(total_weight - 1.0) > 0.01:
                    st.error("비중 합계를 100%로 맞춰주세요!")
                else:
                    with st.spinner("혼합 전략 백테스팅 중..."):
                        # 혼합 전략 계산
                        def run_hybrid_backtest(df_data, weights, period_name):
                            """혼합 전략 백테스팅"""
                            # 총 투자금 설정
                            if is_us_stock:
                                total_budget = 1000  # $1000
                            else:
                                total_budget = 1000000  # 100만원
                            
                            # 각 전략별 자금 배분
                            budget_1sigma = total_budget * weights[0]
                            budget_2sigma = total_budget * weights[1]
                            budget_dca = total_budget * weights[2]
                            
                            # 각 전략 수익률 계산 (실제 백테스팅 결과 활용)
                            if period_name == "1년":
                                return_1sigma = results_1sigma_1year['total_return'] if results_1sigma_1year['total_investment'] > 0 else 0
                                return_2sigma = results_2sigma_1year['total_return'] if results_2sigma_1year['total_investment'] > 0 else 0
                                return_dca = comparison_1y['dca']['total_return']
                            else:
                                return_1sigma = results_1sigma_5year['total_return'] if results_1sigma_5year['total_investment'] > 0 else 0
                                return_2sigma = results_2sigma_5year['total_return'] if results_2sigma_5year['total_investment'] > 0 else 0
                                return_dca = comparison_5y['dca']['total_return']
                            
                            # 가중 평균 수익률
                            hybrid_return = (
                                weights[0] * return_1sigma +
                                weights[1] * return_2sigma +
                                weights[2] * return_dca
                            )
                            
                            # 각 전략의 기여도
                            contribution_1sigma = weights[0] * return_1sigma
                            contribution_2sigma = weights[1] * return_2sigma
                            contribution_dca = weights[2] * return_dca
                            
                            return {
                                'total_return': hybrid_return,
                                'contributions': {
                                    '1σ': contribution_1sigma,
                                    '2σ': contribution_2sigma,
                                    'DCA': contribution_dca
                                },
                                'individual_returns': {
                                    '1σ': return_1sigma,
                                    '2σ': return_2sigma,
                                    'DCA': return_dca
                                }
                            }
                        
                        # 1년, 5년 혼합 전략 실행
                        weights = [weight_1sigma, weight_2sigma, weight_dca]
                        hybrid_1y = run_hybrid_backtest(df_1year, weights, "1년")
                        hybrid_5y = run_hybrid_backtest(df_5year, weights, "5년")
                        
                        # 결과 표시
                        st.success("✅ 혼합 전략 분석 완료!")
                        
                        # 혼합 전략 성과
                        st.markdown("### 📊 혼합 전략 성과")
                        
                        col_hybrid1, col_hybrid2 = st.columns(2)
                        
                        with col_hybrid1:
                            st.markdown("**1년 성과**")
                            st.metric("혼합 전략 수익률", f"{hybrid_1y['total_return']:.2f}%",
                                     delta=f"{hybrid_1y['total_return']:.2f}%")
                            
                            # 기여도 분석
                            st.markdown("**전략별 기여도**")
                            for strategy, contribution in hybrid_1y['contributions'].items():
                                st.write(f"• {strategy}: {contribution:+.2f}%")
                        
                        with col_hybrid2:
                            st.markdown("**5년 성과**")
                            st.metric("혼합 전략 수익률", f"{hybrid_5y['total_return']:.2f}%",
                                     delta=f"{hybrid_5y['total_return']:.2f}%")
                            
                            # 기여도 분석
                            st.markdown("**전략별 기여도**")
                            for strategy, contribution in hybrid_5y['contributions'].items():
                                st.write(f"• {strategy}: {contribution:+.2f}%")
                        
                        # 전체 전략 비교 (혼합 전략 포함)
                        st.markdown("### 📈 전체 전략 비교")
                        
                        # 비교 차트 생성
                        comparison_data = {
                            '전략': ['1σ', '2σ', 'DCA', '혼합'],
                            '1년 수익률': [
                                results_1sigma_1year['total_return'] if results_1sigma_1year['total_investment'] > 0 else 0,
                                results_2sigma_1year['total_return'] if results_2sigma_1year['total_investment'] > 0 else 0,
                                comparison_1y['dca']['total_return'],
                                hybrid_1y['total_return']
                            ],
                            '5년 수익률': [
                                results_1sigma_5year['total_return'] if results_1sigma_5year['total_investment'] > 0 else 0,
                                results_2sigma_5year['total_return'] if results_2sigma_5year['total_investment'] > 0 else 0,
                                comparison_5y['dca']['total_return'],
                                hybrid_5y['total_return']
                            ]
                        }
                        
                        df_comparison = pd.DataFrame(comparison_data)
                        
                        # 그룹 바 차트
                        fig_comparison = go.Figure()
                        
                        fig_comparison.add_trace(go.Bar(
                            name='1년',
                            x=df_comparison['전략'],
                            y=df_comparison['1년 수익률'],
                            text=[f'{y:.1f}%' for y in df_comparison['1년 수익률']],
                            textposition='auto',
                            marker_color='lightblue'
                        ))
                        
                        fig_comparison.add_trace(go.Bar(
                            name='5년',
                            x=df_comparison['전략'],
                            y=df_comparison['5년 수익률'],
                            text=[f'{y:.1f}%' for y in df_comparison['5년 수익률']],
                            textposition='auto',
                            marker_color='darkblue'
                        ))
                        
                        fig_comparison.update_layout(
                            title="전략별 수익률 비교 (혼합 전략 포함)",
                            xaxis_title="투자 전략",
                            yaxis_title="수익률 (%)",
                            barmode='group',
                            height=400
                        )
                        
                        st.plotly_chart(fig_comparison, use_container_width=True)
                        
                        # 인사이트
                        st.markdown("### 💡 핵심 인사이트")
                        
                        # 최고 수익률 전략 찾기
                        best_1y_idx = df_comparison['1년 수익률'].idxmax()
                        best_5y_idx = df_comparison['5년 수익률'].idxmax()
                        
                        insights = []
                        
                        if df_comparison.loc[best_1y_idx, '전략'] == '혼합':
                            insights.append("✅ 혼합 전략이 1년 기준 최고 수익률 달성")
                        
                        if df_comparison.loc[best_5y_idx, '전략'] == '혼합':
                            insights.append("✅ 혼합 전략이 5년 기준 최고 수익률 달성")
                        
                        # 리스크 분산 효과
                        if hybrid_5y['total_return'] > min(hybrid_5y['individual_returns'].values()):
                            insights.append("✅ 전략 혼합으로 리스크 분산 효과 확인")
                        
                        # 안정성
                        if abs(hybrid_1y['total_return'] - hybrid_5y['total_return']) < 10:
                            insights.append("✅ 혼합 전략이 단기/장기 모두 안정적")
                        
                        for insight in insights:
                            st.info(insight)
            
            # 경고 문구
            st.warning("""
            ⚠️ **투자 유의사항**
            - 과거 성과가 미래 수익을 보장하지 않습니다
            - 실제 투자 시 거래 비용과 세금을 고려하세요
            - 개인의 투자 성향과 재무 상황을 고려한 신중한 결정이 필요합니다
            """)
        else:
            st.info("백테스팅 실행 버튼을 클릭하여 분석을 시작하세요.")