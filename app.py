import streamlit as st
import yfinance as yf
from pykrx import stock
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import json
import os
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

# 저장 파일 경로
SAVE_FILE = 'saved_stocks.json'

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
            
            # 모든 값 가져오기
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
                for symbol, info in stocks.items():
                    try:
                        df = analyzer.get_stock_data(symbol, info['type'])
                        if df is not None:
                            stats = analyzer.calculate_sigma_levels(df)
                            info['stats'] = stats
                            info['df'] = df
                    except Exception as e:
                        st.warning(f"{symbol} 데이터 로드 실패: {e}")
                
                st.session_state.monitoring_stocks = stocks
                st.session_state.stocks_loaded = True
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

def save_stocks():
    """모니터링 종목을 JSON 파일에 저장"""
    try:
        stocks_to_save = {}
        for symbol, info in st.session_state.monitoring_stocks.items():
            stocks_to_save[symbol] = {
                'name': info['name'],
                'type': info['type']
            }
        
        with open(SAVE_FILE, 'w', encoding='utf-8') as f:
            json.dump(stocks_to_save, f, ensure_ascii=False, indent=2)
        
        st.success("✅ 저장 완료!")
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

def load_saved_stocks():
    """JSON 파일에서 저장된 종목 불러오기"""
    try:
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        st.error(f"파일 로드 실패: {e}")
        return {}

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
    saved_stocks = load_saved_stocks()

    if saved_stocks and not st.session_state.stocks_loaded:
        if st.button("📂 저장된 종목 불러오기", use_container_width=True):
            analyzer = StockAnalyzer()
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for idx, (symbol, info) in enumerate(saved_stocks.items()):
                status_text.text(f"불러오는 중: {info['name']} ({symbol})")
                progress_bar.progress((idx + 1) / len(saved_stocks))
                
                df = analyzer.get_stock_data(symbol, info['type'])
                if df is not None:
                    stats = analyzer.calculate_sigma_levels(df)
                    st.session_state.monitoring_stocks[symbol] = {
                        'name': info['name'],
                        'type': info['type'],
                        'stats': stats,
                        'df': df
                    }
            
            st.session_state.stocks_loaded = True
            progress_bar.empty()
            status_text.empty()
            st.success(f"✅ {len(st.session_state.monitoring_stocks)}개 종목 로드 완료!")
            st.rerun()
    
    elif st.session_state.monitoring_stocks:
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
    
    # 백테스팅 입력 섹션 (전체 너비 사용)
    # 종목 선택 - 분석 결과 종목과 연동
    if 'current_analysis' in st.session_state:
        analysis = st.session_state.current_analysis
        selected_symbol = analysis['symbol']
        st.info(f"📊 백테스팅 종목: {analysis['name']} ({analysis['symbol']})")
    else:
        st.info("📊 먼저 탭 1에서 종목을 검색하고 분석해주세요.")
        selected_symbol = None
    
    # 투자 전략
    strategy = st.radio("투자 전략", ["1σ 이상 하락시 매수", "2σ 이상 하락시 매수"])
    
    # 투자 금액 설정
    st.markdown("**투자 금액 설정**")
    col1_1, col1_2, col1_3 = st.columns(3)
    
    with col1_1:
        amount_1sigma = st.number_input("1σ 하락시", min_value=0, value=100, disabled=(strategy=="2σ 이상 하락시 매수"))
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
            
            # 백테스팅 함수 정의
            def run_backtest(df_data, period_name):
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
                    
                    # 1σ 하락 시 (1σ 전략일 때만)
                    elif strategy == "1σ 이상 하락시 매수" and current_return <= sigma_1:
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
            
            # 미국 주식인지 확인
            is_us_stock = analysis['type'] == 'US'
            
            # 백테스팅 실행
            with st.spinner("백테스팅 분석 중..."):
                # 기존 시그마 기반 백테스팅
                results_1year = run_backtest(df_1year, "1년")
                results_5year = run_backtest(df_5year, "5년")
            
            # 결과 표시
            st.success("✅ 백테스팅 완료!")
            
            # 결과 비교 (1년 vs 5년)
            if results_1year['buy_count'] > 0 or results_5year['buy_count'] > 0:
                st.markdown("#### 📊 백테스팅 결과 비교")
                
                col_a, col_b = st.columns(2)
                
                with col_a:
                    st.markdown("**최근 1년 결과**")
                    if results_1year['buy_count'] > 0:
                        # 첫 번째 행: 매수횟수, 총 투자금, 평균매수단가, 보유주식수
                        col_a1, col_a2, col_a3, col_a4 = st.columns(4)
                        with col_a1:
                            st.metric("매수 횟수", f"{results_1year['buy_count']}회")
                        with col_a2:
                            if is_us_stock:
                                st.metric("총 투자금", f"${results_1year['total_investment']:,.0f}")
                            else:
                                st.metric("총 투자금", f"₩{results_1year['total_investment']:,.0f}")
                        with col_a3:
                            if is_us_stock:
                                st.metric("평균 매수 단가", f"${results_1year['avg_price']:,.2f}")
                            else:
                                st.metric("평균 매수 단가", f"₩{results_1year['avg_price']:,.0f}")
                        with col_a4:
                            st.metric("보유 주식수", f"{results_1year['total_shares']:.2f}주")
                        
                        # 두 번째 행: 현재 평가금액, 총 수익률
                        col_a5, col_a6 = st.columns(2)
                        with col_a5:
                            if is_us_stock:
                                st.metric("현재 평가금액", f"${results_1year['current_value']:,.0f}")
                            else:
                                st.metric("현재 평가금액", f"₩{results_1year['current_value']:,.0f}")
                        with col_a6:
                            st.metric("총 수익률", f"{results_1year['total_return']:+.2f}%")
                        
                        # 1년 매수 내역 expander
                        if results_1year['buy_history']:
                            with st.expander(f"📈 최근 1년 매수 내역 ({len(results_1year['buy_history'])}건)", expanded=False):
                                buy_df_1year = pd.DataFrame(results_1year['buy_history'])
                                buy_df_1year['날짜'] = buy_df_1year['date'].dt.strftime('%Y.%m.%d')
                                
                                if is_us_stock:
                                    buy_df_1year['가격'] = buy_df_1year['price'].apply(lambda x: f"${x:,.2f}")
                                    buy_df_1year['투자금'] = buy_df_1year['investment'].apply(lambda x: f"${x:,.0f}")
                                else:
                                    buy_df_1year['가격'] = buy_df_1year['price'].apply(lambda x: f"₩{x:,.0f}")
                                    buy_df_1year['투자금'] = buy_df_1year['investment'].apply(lambda x: f"₩{x:,.0f}")
                                
                                buy_df_1year['수익률'] = buy_df_1year['return'].apply(lambda x: f"{x:.2f}%")
                                buy_df_1year['시그마 레벨'] = buy_df_1year['sigma_level']
                                buy_df_1year['주식수'] = buy_df_1year['shares'].apply(lambda x: f"{x:.2f}주")
                                
                                display_df_1year = buy_df_1year[['날짜', '가격', '수익률', '시그마 레벨', '투자금', '주식수']]
                                st.dataframe(display_df_1year, use_container_width=True, hide_index=True)
                    else:
                        st.info("매수 내역 없음")
                
                with col_b:
                    st.markdown("**최근 5년 결과**")
                    if results_5year['buy_count'] > 0:
                        # 첫 번째 행: 매수횟수, 총 투자금, 평균매수단가, 보유주식수
                        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
                        with col_b1:
                            st.metric("매수 횟수", f"{results_5year['buy_count']}회")
                        with col_b2:
                            if is_us_stock:
                                st.metric("총 투자금", f"${results_5year['total_investment']:,.0f}")
                            else:
                                st.metric("총 투자금", f"₩{results_5year['total_investment']:,.0f}")
                        with col_b3:
                            if is_us_stock:
                                st.metric("평균 매수 단가", f"${results_5year['avg_price']:,.2f}")
                            else:
                                st.metric("평균 매수 단가", f"₩{results_5year['avg_price']:,.0f}")
                        with col_b4:
                            st.metric("보유 주식수", f"{results_5year['total_shares']:.2f}주")
                        
                        # 두 번째 행: 현재 평가금액, 총 수익률
                        col_b5, col_b6 = st.columns(2)
                        with col_b5:
                            if is_us_stock:
                                st.metric("현재 평가금액", f"${results_5year['current_value']:,.0f}")
                            else:
                                st.metric("현재 평가금액", f"₩{results_5year['current_value']:,.0f}")
                        with col_b6:
                            st.metric("총 수익률", f"{results_5year['total_return']:+.2f}%")
                        
                        # 5년 매수 내역 expander
                        if results_5year['buy_history']:
                            with st.expander(f"📈 최근 5년 매수 내역 ({len(results_5year['buy_history'])}건)", expanded=False):
                                buy_df_5year = pd.DataFrame(results_5year['buy_history'])
                                buy_df_5year['날짜'] = buy_df_5year['date'].dt.strftime('%Y.%m.%d')
                                
                                if is_us_stock:
                                    buy_df_5year['가격'] = buy_df_5year['price'].apply(lambda x: f"${x:,.2f}")
                                    buy_df_5year['투자금'] = buy_df_5year['investment'].apply(lambda x: f"${x:,.0f}")
                                else:
                                    buy_df_5year['가격'] = buy_df_5year['price'].apply(lambda x: f"₩{x:,.0f}")
                                    buy_df_5year['투자금'] = buy_df_5year['investment'].apply(lambda x: f"₩{x:,.0f}")
                                
                                buy_df_5year['수익률'] = buy_df_5year['return'].apply(lambda x: f"{x:.2f}%")
                                buy_df_5year['시그마 레벨'] = buy_df_5year['sigma_level']
                                buy_df_5year['주식수'] = buy_df_5year['shares'].apply(lambda x: f"{x:.2f}주")
                                
                                display_df_5year = buy_df_5year[['날짜', '가격', '수익률', '시그마 레벨', '투자금', '주식수']]
                                st.dataframe(display_df_5year, use_container_width=True, hide_index=True)
                    else:
                        st.info("매수 내역 없음")
                
                # DCA vs 일시불 투자 비교
                if results_1year['buy_count'] > 0 or results_5year['buy_count'] > 0:
                    st.markdown("---")
                    st.markdown("#### 💰 DCA vs 일시불 투자 비교")
                    

                    
                    col_dca_1y, col_dca_5y = st.columns(2)
                    
                    # DCA vs 일시불 비교 함수
                    def run_dca_vs_lump_sum_comparison(df_data, total_investment, period_months):
                        # DCA 투자 (매월 10일 종가)
                        dca_investment = 0
                        dca_shares = 0
                        dca_buy_count = 0
                        monthly_amount = total_investment / period_months
                        
                        # 일시불 투자 (1년 전 또는 5년 전)
                        if period_months == 12:  # 1년 결과
                            lump_sum_price = df_data['Close'].iloc[-252]  # 1년 전 가격
                        else:  # 5년 결과
                            lump_sum_price = df_data['Close'].iloc[0]  # 5년 전 가격 (첫날)
                        
                        lump_sum_shares = total_investment / lump_sum_price
                        lump_sum_investment = total_investment
                        
                        # 매월 10일 찾기 (정확히 12개월 또는 60개월)
                        target_months = period_months
                        found_months = 0
                        last_month = -1
                        
                        for i in range(len(df_data)):
                            current_date = df_data.index[i]
                            current_month = current_date.month
                            
                            # 매월 10일 또는 10일 이후 첫 거래일
                            if (current_date.day >= 10 and current_month != last_month and found_months < target_months):
                                current_price = df_data['Close'].iloc[i]
                                shares = monthly_amount / current_price
                                dca_investment += monthly_amount
                                dca_shares += shares
                                dca_buy_count += 1
                                found_months += 1
                                last_month = current_month
                        
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
                                'total_investment': total_investment,  # 시그마 하락시의 총투자금과 동일
                                'monthly_amount': monthly_amount,
                                'avg_price': dca_avg_price,
                                'total_shares': dca_shares,
                                'current_value': dca_current_value,
                                'total_return': dca_total_return
                            },
                            'lump_sum': {
                                'buy_count': 1,
                                'total_investment': lump_sum_investment,
                                'avg_price': lump_sum_avg_price,
                                'total_shares': lump_sum_shares,
                                'current_value': lump_sum_current_value,
                                'total_return': lump_sum_total_return
                            }
                        }
                    
                    # 1년 결과 (왼쪽)
                    with col_dca_1y:
                        st.markdown("**최근 1년 결과**")
                        
                        if results_1year['buy_count'] > 0:
                            # 1년 총 투자금을 기준으로 DCA 계산
                            total_investment_1y = results_1year['total_investment']
                            
                            # 1년 데이터로 DCA vs 일시불 비교
                            df_1year = analysis['df'].tail(252)
                            comparison_1y = run_dca_vs_lump_sum_comparison(df_1year, total_investment_1y, 12)
                            
                            # DCA 결과
                            st.markdown("### 📈 DCA (매월 정액)")
                            # 첫 번째 행: 매수횟수, 총 투자금, 매월 투자금, 평균매수단가, 보유주식수
                            col_dca1_1, col_dca1_2, col_dca1_3, col_dca1_4, col_dca1_5 = st.columns(5)
                            with col_dca1_1:
                                st.metric("매수 횟수", f"{comparison_1y['dca']['buy_count']}회", delta=None)
                            with col_dca1_2:
                                if is_us_stock:
                                    st.metric("총 투자금", f"${comparison_1y['dca']['total_investment']:,.0f}", delta=None)
                                else:
                                    st.metric("총 투자금", f"₩{comparison_1y['dca']['total_investment']:,.0f}", delta=None)
                            with col_dca1_3:
                                if is_us_stock:
                                    st.metric("매월 투자금", f"${comparison_1y['dca']['monthly_amount']:,.0f}", delta=None)
                                else:
                                    st.metric("매월 투자금", f"₩{comparison_1y['dca']['monthly_amount']:,.0f}", delta=None)
                            with col_dca1_4:
                                if is_us_stock:
                                    st.metric("평균 매수 단가", f"${comparison_1y['dca']['avg_price']:,.2f}", delta=None)
                                else:
                                    st.metric("평균 매수 단가", f"₩{comparison_1y['dca']['avg_price']:,.0f}", delta=None)
                            with col_dca1_5:
                                st.metric("보유 주식수", f"{comparison_1y['dca']['total_shares']:.2f}주", delta=None)
                            
                            # 두 번째 행: 현재 평가금액, 총 수익률
                            col_dca1_6, col_dca1_7 = st.columns(2)
                            with col_dca1_6:
                                if is_us_stock:
                                    st.metric("현재 평가금액", f"${comparison_1y['dca']['current_value']:,.0f}", delta=None)
                                else:
                                    st.metric("현재 평가금액", f"₩{comparison_1y['dca']['current_value']:,.0f}", delta=None)
                            with col_dca1_7:
                                st.metric("총 수익률", f"{comparison_1y['dca']['total_return']:+.2f}%", delta=None)
                            
                            # DCA 매수 내역 expander
                            if comparison_1y['dca']['buy_count'] > 0:
                                with st.expander(f"📈 DCA 매수 내역 ({comparison_1y['dca']['buy_count']}건)", expanded=False):
                                    # DCA 매수 내역 생성
                                    dca_buy_history = []
                                    df_1year = analysis['df'].tail(252)
                                    monthly_amount = comparison_1y['dca']['monthly_amount']
                                    found_months = 0
                                    last_month = -1
                                    
                                    for i in range(len(df_1year)):
                                        current_date = df_1year.index[i]
                                        current_month = current_date.month
                                        
                                        # 매월 10일 또는 10일 이후 첫 거래일
                                        if (current_date.day >= 10 and current_month != last_month and found_months < 12):
                                            current_price = df_1year['Close'].iloc[i]
                                            shares = monthly_amount / current_price
                                            dca_buy_history.append({
                                                'date': current_date,
                                                'price': current_price,
                                                'investment': monthly_amount,
                                                'shares': shares
                                            })
                                            found_months += 1
                                            last_month = current_month
                                    
                                    if dca_buy_history:
                                        dca_df = pd.DataFrame(dca_buy_history)
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
                            
                            # 일시불 결과
                            st.markdown("### 💰 일시불 (1년 전)")
                            # 첫 번째 행: 매수횟수, 총 투자금, 평균매수단가, 보유주식수
                            col_lump1_1, col_lump1_2, col_lump1_3, col_lump1_4 = st.columns(4)
                            with col_lump1_1:
                                st.metric("매수 횟수", f"{comparison_1y['lump_sum']['buy_count']}회", delta=None)
                            with col_lump1_2:
                                if is_us_stock:
                                    st.metric("총 투자금", f"${comparison_1y['lump_sum']['total_investment']:,.0f}", delta=None)
                                else:
                                    st.metric("총 투자금", f"₩{comparison_1y['lump_sum']['total_investment']:,.0f}", delta=None)
                            with col_lump1_3:
                                if is_us_stock:
                                    st.metric("평균 매수 단가", f"${comparison_1y['lump_sum']['avg_price']:,.2f}", delta=None)
                                else:
                                    st.metric("평균 매수 단가", f"₩{comparison_1y['lump_sum']['avg_price']:,.0f}", delta=None)
                            with col_lump1_4:
                                st.metric("보유 주식수", f"{comparison_1y['lump_sum']['total_shares']:.2f}주", delta=None)
                            
                            # 두 번째 행: 현재 평가금액, 총 수익률
                            col_lump1_5, col_lump1_6 = st.columns(2)
                            with col_lump1_5:
                                if is_us_stock:
                                    st.metric("현재 평가금액", f"${comparison_1y['lump_sum']['current_value']:,.0f}", delta=None)
                                else:
                                    st.metric("현재 평가금액", f"₩{comparison_1y['lump_sum']['current_value']:,.0f}", delta=None)
                            with col_lump1_6:
                                st.metric("총 수익률", f"{comparison_1y['lump_sum']['total_return']:+.2f}%", delta=None)
                        else:
                            st.info("1년 매수 내역 없음")
                    
                    # 5년 결과 (오른쪽)
                    with col_dca_5y:
                        st.markdown("**최근 5년 결과**")
                        
                        if results_5year['buy_count'] > 0:
                            # 5년 총 투자금을 기준으로 DCA 계산
                            total_investment_5y = results_5year['total_investment']
                            
                            # 5년 데이터로 DCA vs 일시불 비교
                            df_5year = analysis['df']
                            comparison_5y = run_dca_vs_lump_sum_comparison(df_5year, total_investment_5y, 60)
                            
                            # DCA 결과
                            st.markdown("### 📈 DCA (매월 정액)")
                            # 첫 번째 행: 매수횟수, 총 투자금, 매월 투자금, 평균매수단가, 보유주식수
                            col_dca5_1, col_dca5_2, col_dca5_3, col_dca5_4, col_dca5_5 = st.columns(5)
                            with col_dca5_1:
                                st.metric("매수 횟수", f"{comparison_5y['dca']['buy_count']}회", delta=None)
                            with col_dca5_2:
                                if is_us_stock:
                                    st.metric("총 투자금", f"${comparison_5y['dca']['total_investment']:,.0f}", delta=None)
                                else:
                                    st.metric("총 투자금", f"₩{comparison_5y['dca']['total_investment']:,.0f}", delta=None)
                            with col_dca5_3:
                                if is_us_stock:
                                    st.metric("매월 투자금", f"${comparison_5y['dca']['monthly_amount']:,.0f}", delta=None)
                                else:
                                    st.metric("매월 투자금", f"₩{comparison_5y['dca']['monthly_amount']:,.0f}", delta=None)
                            with col_dca5_4:
                                if is_us_stock:
                                    st.metric("평균 매수 단가", f"${comparison_5y['dca']['avg_price']:,.2f}", delta=None)
                                else:
                                    st.metric("평균 매수 단가", f"₩{comparison_5y['dca']['avg_price']:,.0f}", delta=None)
                            with col_dca5_5:
                                st.metric("보유 주식수", f"{comparison_5y['dca']['total_shares']:.2f}주", delta=None)
                            
                            # 두 번째 행: 현재 평가금액, 총 수익률
                            col_dca5_6, col_dca5_7 = st.columns(2)
                            with col_dca5_6:
                                if is_us_stock:
                                    st.metric("현재 평가금액", f"${comparison_5y['dca']['current_value']:,.0f}", delta=None)
                                else:
                                    st.metric("현재 평가금액", f"₩{comparison_5y['dca']['current_value']:,.0f}", delta=None)
                            with col_dca5_7:
                                st.metric("총 수익률", f"{comparison_5y['dca']['total_return']:+.2f}%", delta=None)
                            
                            # DCA 매수 내역 expander (5년)
                            if comparison_5y['dca']['buy_count'] > 0:
                                with st.expander(f"📈 DCA 매수 내역 ({comparison_5y['dca']['buy_count']}건)", expanded=False):
                                    # DCA 매수 내역 생성
                                    dca_buy_history_5y = []
                                    df_5year = analysis['df']
                                    monthly_amount_5y = comparison_5y['dca']['monthly_amount']
                                    found_months_5y = 0
                                    last_month_5y = -1
                                    
                                    for i in range(len(df_5year)):
                                        current_date = df_5year.index[i]
                                        current_month = current_date.month
                                        
                                        # 매월 10일 또는 10일 이후 첫 거래일
                                        if (current_date.day >= 10 and current_month != last_month_5y and found_months_5y < 60):
                                            current_price = df_5year['Close'].iloc[i]
                                            shares = monthly_amount_5y / current_price
                                            dca_buy_history_5y.append({
                                                'date': current_date,
                                                'price': current_price,
                                                'investment': monthly_amount_5y,
                                                'shares': shares
                                            })
                                            found_months_5y += 1
                                            last_month_5y = current_month
                                    
                                    if dca_buy_history_5y:
                                        dca_df_5y = pd.DataFrame(dca_buy_history_5y)
                                        dca_df_5y['날짜'] = dca_df_5y['date'].dt.strftime('%Y.%m.%d')
                                        
                                        if is_us_stock:
                                            dca_df_5y['가격'] = dca_df_5y['price'].apply(lambda x: f"${x:,.2f}")
                                            dca_df_5y['투자금'] = dca_df_5y['investment'].apply(lambda x: f"${x:,.0f}")
                                        else:
                                            dca_df_5y['가격'] = dca_df_5y['price'].apply(lambda x: f"₩{x:,.0f}")
                                            dca_df_5y['투자금'] = dca_df_5y['investment'].apply(lambda x: f"₩{x:,.0f}")
                                        
                                        dca_df_5y['주식수'] = dca_df_5y['shares'].apply(lambda x: f"{x:.2f}주")
                                        
                                        display_dca_df_5y = dca_df_5y[['날짜', '가격', '투자금', '주식수']]
                                        st.dataframe(display_dca_df_5y, use_container_width=True, hide_index=True)
                            
                            # 일시불 결과
                            st.markdown("### 💰 일시불 (5년 전)")
                            # 첫 번째 행: 매수횟수, 총 투자금, 평균매수단가, 보유주식수
                            col_lump5_1, col_lump5_2, col_lump5_3, col_lump5_4 = st.columns(4)
                            with col_lump5_1:
                                st.metric("매수 횟수", f"{comparison_5y['lump_sum']['buy_count']}회", delta=None)
                            with col_lump5_2:
                                if is_us_stock:
                                    st.metric("총 투자금", f"${comparison_5y['lump_sum']['total_investment']:,.0f}", delta=None)
                                else:
                                    st.metric("총 투자금", f"₩{comparison_5y['lump_sum']['total_investment']:,.0f}", delta=None)
                            with col_lump5_3:
                                if is_us_stock:
                                    st.metric("평균 매수 단가", f"${comparison_5y['lump_sum']['avg_price']:,.2f}", delta=None)
                                else:
                                    st.metric("평균 매수 단가", f"₩{comparison_5y['lump_sum']['avg_price']:,.0f}", delta=None)
                            with col_lump5_4:
                                st.metric("보유 주식수", f"{comparison_5y['lump_sum']['total_shares']:.2f}주", delta=None)
                            
                            # 두 번째 행: 현재 평가금액, 총 수익률
                            col_lump5_5, col_lump5_6 = st.columns(2)
                            with col_lump5_5:
                                if is_us_stock:
                                    st.metric("현재 평가금액", f"${comparison_5y['lump_sum']['current_value']:,.0f}", delta=None)
                                else:
                                    st.metric("현재 평가금액", f"₩{comparison_5y['lump_sum']['current_value']:,.0f}", delta=None)
                            with col_lump5_6:
                                st.metric("총 수익률", f"{comparison_5y['lump_sum']['total_return']:+.2f}%", delta=None)
                        else:
                            st.info("5년 매수 내역 없음")
                
                # 수익률 비교 그래프
                st.markdown("---")
                st.markdown("#### 📊 수익률 비교 그래프")
                
                col_graph_1y, col_graph_5y = st.columns(2)
                
                # 1년 결과 그래프 (왼쪽)
                with col_graph_1y:
                    if results_1year['buy_count'] > 0:
                        st.markdown("**1년 결과 수익률 비교**")
                        
                        # 1년 수익률 데이터
                        sigma_return_1y = results_1year['total_return']
                        dca_return_1y = comparison_1y['dca']['total_return']
                        lump_sum_return_1y = comparison_1y['lump_sum']['total_return']
                        
                        # 1년 그래프
                        fig_1y = go.Figure()
                        fig_1y.add_trace(go.Bar(
                            x=['시그마 하락시', 'DCA', '일시불'],
                            y=[sigma_return_1y, dca_return_1y, lump_sum_return_1y],
                            text=[f'{sigma_return_1y:+.2f}%', f'{dca_return_1y:+.2f}%', f'{lump_sum_return_1y:+.2f}%'],
                            textposition='auto',
                            marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
                        ))
                        fig_1y.update_layout(
                            title="1년 수익률 비교",
                            xaxis_title="투자 전략",
                            yaxis_title="수익률 (%)",
                            height=400
                        )
                        st.plotly_chart(fig_1y, use_container_width=True)
                    else:
                        st.info("1년 매수 내역 없음")
                
                # 5년 결과 그래프 (오른쪽)
                with col_graph_5y:
                    if results_5year['buy_count'] > 0:
                        st.markdown("**5년 결과 수익률 비교**")
                        
                        # 5년 수익률 데이터
                        sigma_return_5y = results_5year['total_return']
                        dca_return_5y = comparison_5y['dca']['total_return']
                        lump_sum_return_5y = comparison_5y['lump_sum']['total_return']
                        
                        # 5년 그래프
                        fig_5y = go.Figure()
                        fig_5y.add_trace(go.Bar(
                            x=['시그마 하락시', 'DCA', '일시불'],
                            y=[sigma_return_5y, dca_return_5y, lump_sum_return_5y],
                            text=[f'{sigma_return_5y:+.2f}%', f'{dca_return_5y:+.2f}%', f'{lump_sum_return_5y:+.2f}%'],
                            textposition='auto',
                            marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
                        ))
                        fig_5y.update_layout(
                            title="5년 수익률 비교",
                            xaxis_title="투자 전략",
                            yaxis_title="수익률 (%)",
                            height=400
                        )
                        st.plotly_chart(fig_5y, use_container_width=True)
                    else:
                        st.info("5년 매수 내역 없음")
                
                # AI 투자 보고서
                st.markdown("---")
                st.markdown("#### 📋 AI 투자 분석 보고서")
                
                # 보고서 생성 함수
                def generate_investment_report(results_1y, results_5y, comparison_1y, comparison_5y, analysis):
                    report = []
                    
                    # 기본 정보
                    stock_name = analysis['name']
                    stock_symbol = analysis['symbol']
                    report.append(f"### 📊 {stock_name} ({stock_symbol}) 투자 분석")
                    report.append("")
                    
                    # 1년과 5년 결과를 컬럼으로 나누기
                    col_1y, col_5y = st.columns(2)
                    
                    # 1년 결과 분석 (왼쪽)
                    with col_1y:
                        if results_1y['buy_count'] > 0:
                            st.markdown("#### 📈 1년 투자 성과")
                            
                            # 수익률 비교
                            sigma_1y = results_1y['total_return']
                            dca_1y = comparison_1y['dca']['total_return']
                            lump_1y = comparison_1y['lump_sum']['total_return']
                            
                            best_1y = max(sigma_1y, dca_1y, lump_1y)
                            worst_1y = min(sigma_1y, dca_1y, lump_1y)
                            
                            st.markdown(f"**최고 성과**: {best_1y:+.2f}%")
                            st.markdown(f"**최저 성과**: {worst_1y:+.2f}%")
                            st.markdown(f"**성과 차이**: {best_1y - worst_1y:.2f}%p")
                            st.markdown("")
                            
                            # 전략별 분석
                            if sigma_1y == best_1y:
                                st.markdown("🎯 **시그마 하락시 매수**가 가장 우수한 성과")
                            elif dca_1y == best_1y:
                                st.markdown("📈 **DCA 투자**가 가장 우수한 성과")
                            else:
                                st.markdown("💰 **일시불 투자**가 가장 우수한 성과")
                            
                            # 변동성 분석
                            performance_diff_1y = best_1y - worst_1y
                            if performance_diff_1y > 50:
                                st.markdown("📊 **매우 높은 변동성**: 전략 간 성과 차이가 매우 큼")
                            elif performance_diff_1y > 30:
                                st.markdown("📊 **높은 변동성**: 전략 간 성과 차이가 큼")
                            elif performance_diff_1y > 15:
                                st.markdown("📊 **중간 변동성**: 전략 간 성과 차이가 적당함")
                            else:
                                st.markdown("📊 **안정적 성과**: 전략 간 성과 차이가 적음")
                        else:
                            st.info("1년 매수 내역 없음")
                    
                    # 5년 결과 분석 (오른쪽)
                    with col_5y:
                        if results_5y['buy_count'] > 0:
                            st.markdown("#### 📈 5년 투자 성과")
                            
                            # 수익률 비교
                            sigma_5y = results_5y['total_return']
                            dca_5y = comparison_5y['dca']['total_return']
                            lump_5y = comparison_5y['lump_sum']['total_return']
                            
                            best_5y = max(sigma_5y, dca_5y, lump_5y)
                            worst_5y = min(sigma_5y, dca_5y, lump_5y)
                            
                            st.markdown(f"**최고 성과**: {best_5y:+.2f}%")
                            st.markdown(f"**최저 성과**: {worst_5y:+.2f}%")
                            st.markdown(f"**성과 차이**: {best_5y - worst_5y:.2f}%p")
                            st.markdown("")
                            
                            # 전략별 분석
                            if sigma_5y == best_5y:
                                st.markdown("🎯 **시그마 하락시 매수**가 장기적으로 가장 우수한 성과")
                            elif dca_5y == best_5y:
                                st.markdown("📈 **DCA 투자**가 장기적으로 가장 우수한 성과")
                            else:
                                st.markdown("💰 **일시불 투자**가 장기적으로 가장 우수한 성과")
                            
                            # 변동성 분석
                            performance_diff_5y = best_5y - worst_5y
                            if performance_diff_5y > 50:
                                st.markdown("📊 **매우 높은 변동성**: 전략 간 성과 차이가 매우 큼")
                            elif performance_diff_5y > 30:
                                st.markdown("📊 **높은 변동성**: 전략 간 성과 차이가 큼")
                            elif performance_diff_5y > 15:
                                st.markdown("📊 **중간 변동성**: 전략 간 성과 차이가 적당함")
                            else:
                                st.markdown("📊 **안정적 성과**: 전략 간 성과 차이가 적음")
                            
                            # 장단기 비교는 컬럼 밖으로 이동
                        else:
                            st.info("5년 매수 내역 없음")
                            
                            # 장단기 분석은 함수 밖으로 이동
                    
                    report.append("")
                    
                    # 투자 권장사항
                    report.append("#### 💡 투자 권장사항")
                    
                    if results_1y['buy_count'] > 0 and results_5y['buy_count'] > 0:
                        # 1년과 5년 모두 있는 경우
                        if best_1y > best_5y:
                            report.append("🎯 **단기 투자 권장**: 1년 성과가 5년보다 우수")
                        else:
                            report.append("📈 **장기 투자 권장**: 5년 성과가 1년보다 우수")
                        
                        # 변동성에 따른 권장사항
                        volatility_1y = max(sigma_1y, dca_1y, lump_1y) - min(sigma_1y, dca_1y, lump_1y)
                        volatility_5y = max(sigma_5y, dca_5y, lump_5y) - min(sigma_5y, dca_5y, lump_5y)
                        
                        if volatility_1y > 50 or volatility_5y > 50:
                            report.append("⚠️ **매우 높은 변동성**: 리스크 관리 매우 주의 필요")
                        elif volatility_1y > 30 or volatility_5y > 30:
                            report.append("⚠️ **높은 변동성**: 리스크 관리 주의 필요")
                        elif volatility_1y > 15 or volatility_5y > 15:
                            report.append("📊 **중간 변동성**: 적당한 리스크 관리 필요")
                        else:
                            report.append("✅ **안정적 성과**: 비교적 안정적인 투자 환경")
                        
                        # 최적 전략 추천
                        if sigma_1y == best_1y and sigma_5y == best_5y:
                            report.append("🎯 **시그마 하락시 매수 전략 추천**: 단기/장기 모두 우수")
                        elif dca_1y == best_1y and dca_5y == best_5y:
                            report.append("📈 **DCA 투자 전략 추천**: 단기/장기 모두 우수")
                        elif lump_1y == best_1y and lump_5y == best_5y:
                            report.append("💰 **일시불 투자 전략 추천**: 단기/장기 모두 우수")
                        else:
                            report.append("🔄 **혼합 전략 고려**: 기간별로 다른 전략이 우수")
                    
                    return "\n".join(report)
                
                # ChatGPT 스타일 해석 생성 함수
                def generate_chatgpt_analysis(results_1y, results_5y, comparison_1y, comparison_5y, analysis):
                    analysis_text = []
                    analysis_text.append("### 📊 종합 분석")
                    analysis_text.append("")
                    
                    if results_1y['buy_count'] > 0 and results_5y['buy_count'] > 0:
                        # 1년과 5년 모두 있는 경우
                        sigma_1y = results_1y['total_return']
                        dca_1y = comparison_1y['dca']['total_return']
                        lump_1y = comparison_1y['lump_sum']['total_return']
                        
                        sigma_5y = results_5y['total_return']
                        dca_5y = comparison_5y['dca']['total_return']
                        lump_5y = comparison_5y['lump_sum']['total_return']
                        
                        # 변동성 분석
                        volatility_1y = max(sigma_1y, dca_1y, lump_1y) - min(sigma_1y, dca_1y, lump_1y)
                        volatility_5y = max(sigma_5y, dca_5y, lump_5y) - min(sigma_5y, dca_5y, lump_5y)
                        
                        # 종목별 특성 분석
                        stock_name = analysis['name'].lower()
                        stock_symbol = analysis['symbol'].lower()
                        
                        # 종목별 특성 판단
                        if any(keyword in stock_name or keyword in stock_symbol for keyword in ['leveraged', 'inverse', '2x', '3x', 'ultra', 'proshares', 'direxion']):
                            analysis_text.append("**⚠️ 고위험 종목**")
                            analysis_text.append("레버리지/인버스 ETF 특성으로 단기간 큰 변동성")
                            analysis_text.append("투자 금액 10% 이하로 제한 권장")
                        elif volatility_1y > 50 or volatility_5y > 50:
                            analysis_text.append("**⚠️ 고위험 종목**")
                            analysis_text.append("매우 높은 변동성으로 리스크 관리 매우 주의 필요")
                            analysis_text.append("투자 금액 10% 이하로 제한 권장")
                        elif volatility_1y > 30 or volatility_5y > 30:
                            analysis_text.append("**⚠️ 고위험 종목**")
                            analysis_text.append("높은 변동성으로 리스크 관리 필요")
                            analysis_text.append("투자 금액 10% 이하로 제한 권장")
                        elif volatility_1y > 15 or volatility_5y > 15:
                            analysis_text.append("**📊 중위험 종목**")
                            analysis_text.append("적당한 변동성으로 분산 투자 권장")
                            analysis_text.append("포트폴리오 20-30% 비중으로 분산 투자")
                        else:
                            analysis_text.append("**✅ 저위험 종목**")
                            analysis_text.append("안정적인 성과로 예측 가능한 투자")
                            analysis_text.append("핵심 자산으로 적극 활용 가능")
                        
                        analysis_text.append("")
                        
                        # 최적 전략 분석
                        best_1y = max(sigma_1y, dca_1y, lump_1y)
                        best_5y = max(sigma_5y, dca_5y, lump_5y)
                        
                        analysis_text.append("**🎯 최적 투자 전략**")
                        
                        if sigma_1y == best_1y and sigma_5y == best_5y:
                            analysis_text.append("시그마 하락시 매수 전략 우수")
                            analysis_text.append("시장 하락을 기회로 활용하는 능동적 투자")
                        elif dca_1y == best_1y and dca_5y == best_5y:
                            analysis_text.append("DCA 투자 전략 우수")
                            analysis_text.append("꾸준한 정기 투자로 리스크 분산 및 복리 효과")
                        elif lump_1y == best_1y and lump_5y == best_5y:
                            analysis_text.append("일시불 투자 전략 우수")
                            analysis_text.append("적절한 시점에 대량 투자하는 전략")
                        else:
                            analysis_text.append("혼합 전략 권장")
                            analysis_text.append("기간별로 다른 전략이 효과적")
                        
                        analysis_text.append("")
                        
                        # 투자 기간 권장
                        analysis_text.append("**📈 투자 기간 권장**")
                        
                        if best_5y > best_1y * 2:
                            analysis_text.append("장기 투자 매우 유리")
                            analysis_text.append("복리 효과와 장기 상승 트렌드 활용")
                        elif best_5y > best_1y:
                            analysis_text.append("장기 투자 유리")
                            analysis_text.append("시간을 두고 투자하는 것이 효과적")
                        elif best_1y > best_5y:
                            analysis_text.append("단기 투자 유리")
                            analysis_text.append("최근 시장 상황이 특별히 좋음")
                        else:
                            analysis_text.append("안정적 투자 환경")
                            analysis_text.append("예측 가능한 성과 기대")
                    
                    return "\n".join(analysis_text)
                
                # 보고서 생성 및 표시
                if (results_1year['buy_count'] > 0 or results_5year['buy_count'] > 0):
                    report_text = generate_investment_report(
                        results_1year, results_5year, 
                        comparison_1y, comparison_5y, 
                        analysis
                    )
                    st.markdown(report_text)
                    
                    # 장단기 분석 추가 (1년과 5년 투자성과 바로 아래)
                    if results_1year['buy_count'] > 0 and results_5year['buy_count'] > 0:
                        st.markdown("---")
                        st.markdown("#### 📊 장단기 분석")
                        
                        # 1년과 5년 결과에서 최고 성과 계산
                        sigma_1y = results_1year['total_return']
                        dca_1y = comparison_1y['dca']['total_return']
                        lump_1y = comparison_1y['lump_sum']['total_return']
                        best_1y = max(sigma_1y, dca_1y, lump_1y)
                        
                        sigma_5y = results_5year['total_return']
                        dca_5y = comparison_5y['dca']['total_return']
                        lump_5y = comparison_5y['lump_sum']['total_return']
                        best_5y = max(sigma_5y, dca_5y, lump_5y)
                        
                        # 장단기 비교 요약
                        if best_5y > best_1y * 2:
                            st.success("✅ 장기 투자가 매우 유리: 5년 성과가 1년보다 2배 이상 우수한 성과를 보여 장기 투자를 강력히 권장합니다.")
                        elif best_5y > best_1y:
                            st.success("✅ 장기 투자가 유리: 5년 성과가 1년보다 우수하여 장기 투자를 권장합니다.")
                        elif best_1y > best_5y:
                            st.warning("⚠️ 단기 투자가 유리: 1년 성과가 5년보다 우수하여 단기 투자를 고려해볼 수 있습니다.")
                        else:
                            st.info("📊 안정적 성과: 장단기 성과가 비슷하여 투자 기간 선택에 있어 유연성을 가질 수 있습니다.")
                    
                    # ChatGPT 스타일 해석 추가
                    chatgpt_analysis = generate_chatgpt_analysis(
                        results_1year, results_5year,
                        comparison_1y, comparison_5y,
                        analysis
                    )
                    st.markdown(chatgpt_analysis)
                else:
                    st.info("매수 내역이 없어 분석 보고서를 생성할 수 없습니다.")
            
            # 이전 구조 (단일 결과) 처리
            else:
                # 매수 내역 및 횟수
                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    st.metric("매수 횟수", f"{results['buy_count']}회")
                with col_b:
                    # 미국 주식인지 확인
                    if 'current_analysis' in st.session_state and st.session_state.current_analysis['type'] == 'US':
                        st.metric("총 투자금", f"${results['total_investment']:,.0f}")
                    else:
                        st.metric("총 투자금", f"₩{results['total_investment']:,.0f}")
                with col_c:
                    if results['buy_count'] > 0:
                        # 미국 주식인지 확인
                        if 'current_analysis' in st.session_state and st.session_state.current_analysis['type'] == 'US':
                            st.metric("평균 매수 단가", f"${results['avg_price']:,.2f}")
                        else:
                            st.metric("평균 매수 단가", f"₩{results['avg_price']:,.0f}")
                    else:
                        st.metric("평균 매수 단가", "매수 없음")
                with col_d:
                    if results['buy_count'] > 0:
                        st.metric("총 보유 주식수", f"{results['total_shares']:.2f}주")
                    else:
                        st.metric("총 보유 주식수", "0주")
                
                # 수익률 분석
                if 'current_value' in results and 'total_return' in results and 'annual_return' in results:
                    st.markdown("#### 📊 수익률 분석")
                    col_e, col_f, col_g = st.columns(3)
                    with col_e:
                        # 미국 주식인지 확인
                        if 'current_analysis' in st.session_state and st.session_state.current_analysis['type'] == 'US':
                            st.metric("현재 평가금액", f"${results['current_value']:,.0f}")
                        else:
                            st.metric("현재 평가금액", f"₩{results['current_value']:,.0f}")
                    with col_f:
                        st.metric("총 수익률", f"{results['total_return']:+.2f}%")
                    with col_g:
                        st.metric("연간 수익률", f"{results['annual_return']:+.2f}%")
                else:
                    st.info("수익률 분석을 위해 백테스팅을 다시 실행해주세요.")
                
                # 매수 내역 상세 (접었다 펼쳤다 가능)
                if results['buy_history']:
                    with st.expander(f"📈 매수 내역 ({len(results['buy_history'])}건)", expanded=False):
                        buy_df = pd.DataFrame(results['buy_history'])
                        buy_df['날짜'] = buy_df['date'].dt.strftime('%Y.%m.%d')
                        
                        # 미국 주식인지 확인하여 통화 설정
                        is_us_stock = 'current_analysis' in st.session_state and st.session_state.current_analysis['type'] == 'US'
                        
                        if is_us_stock:
                            buy_df['가격'] = buy_df['price'].apply(lambda x: f"${x:,.2f}")
                            buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"${x:,.0f}")
                        else:
                            buy_df['가격'] = buy_df['price'].apply(lambda x: f"₩{x:,.0f}")
                            buy_df['투자금'] = buy_df['investment'].apply(lambda x: f"₩{x:,.0f}")
                        
                        buy_df['수익률'] = buy_df['return'].apply(lambda x: f"{x:.2f}%")
                        buy_df['시그마 레벨'] = buy_df['sigma_level']
                        buy_df['주식수'] = buy_df['shares'].apply(lambda x: f"{x:.2f}주")
                        
                        display_df = buy_df[['날짜', '가격', '수익률', '시그마 레벨', '투자금', '주식수']]
                        st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.info("매수 내역이 없습니다.")
        else:
            st.info("백테스팅 실행 버튼을 클릭하여 분석을 시작하세요.")