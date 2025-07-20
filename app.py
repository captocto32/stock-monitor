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
warnings.filterwarnings('ignore')

# 페이지 설정
st.set_page_config(
    page_title="주식 하락률 모니터링",
    page_icon="📉",
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

def save_stocks():
    """모니터링 종목을 파일로 저장"""
    save_data = {}
    for symbol, info in st.session_state.monitoring_stocks.items():
        save_data[symbol] = {
            'name': info['name'],
            'type': info['type']
        }
    
    with open(SAVE_FILE, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

def load_saved_stocks():
    """저장된 종목 목록 불러오기"""
    if not os.path.exists(SAVE_FILE):
        return {}
    
    try:
        with open(SAVE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

class StockAnalyzer:
    def __init__(self):
        pass
        
    def search_korean_stock(self, query):
        """한국 주식 검색"""
        try:
            if query.isdigit() and len(query) == 6:
                name = stock.get_market_ticker_name(query)
                if name:
                    return query, name
            else:
                tickers = stock.get_market_ticker_list()
                for ticker in tickers:
                    name = stock.get_market_ticker_name(ticker)
                    if query.upper() in name.upper():
                        return ticker, name
            return None, None
        except:
            return None, None
    
    def get_stock_data(self, symbol, stock_type='KR'):
        """5년간 주가 데이터 가져오기"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365*5)
        
        try:
            if stock_type == 'KR':
                df = stock.get_market_ohlcv(start_date.strftime('%Y%m%d'), 
                                           end_date.strftime('%Y%m%d'), 
                                           symbol)
                if df.empty:
                    return None
            else:
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start_date, end=end_date)
                if df.empty:
                    return None
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                df.columns = ['시가', '고가', '저가', '종가', '거래량']
            
            return df
        except Exception as e:
            st.error(f"데이터 가져오기 실패: {e}")
            return None
    
    def calculate_sigma_levels(self, df):
        """시그마 레벨 계산 (5년 + 1년)"""
        df['일일수익률'] = df['종가'].pct_change() * 100
        df = df.dropna()
    
        # 5년 전체 데이터
        returns_5y = df['일일수익률'].values
        mean_5y = df['일일수익률'].mean()
        std_5y = df['일일수익률'].std()
    
        #최근 1년 데이터
        one_year_ago = datetime.now() - timedelta(days=365)
        # 시간대 제거 또는 맞춤
        if df.index.tz is not None:
            one_year_ago = pd.Timestamp(one_year_ago).tz_localize(df.index.tz)
        else:
            one_year_ago = pd.Timestamp(one_year_ago)
    
        df_1y = df[df.index >= one_year_ago]

        # 1년 데이터가 충분한지 확인
        if len(df_1y) > 20:  # 최소 20일 이상의 데이터가 있을 때만
            returns_1y = df_1y['일일수익률'].values
            mean_1y = df_1y['일일수익률'].mean()
            std_1y = df_1y['일일수익률'].std()
            
            sigma_1_1y = mean_1y - std_1y
            sigma_2_1y = mean_1y - 2 * std_1y
            sigma_3_1y = mean_1y - 3 * std_1y
            
            actual_prob_1_1y = (returns_1y <= sigma_1_1y).sum() / len(returns_1y) * 100
            actual_prob_2_1y = (returns_1y <= sigma_2_1y).sum() / len(returns_1y) * 100
            actual_prob_3_1y = (returns_1y <= sigma_3_1y).sum() / len(returns_1y) * 100
        else:
            # 1년 데이터가 부족한 경우 5년 데이터와 동일하게 설정
            returns_1y = returns_5y  # 이 줄을 먼저!
            mean_1y = mean_5y
            std_1y = std_5y
            sigma_1_1y = mean_1y - std_1y
            sigma_2_1y = mean_1y - 2 * std_1y
            sigma_3_1y = mean_1y - 3 * std_1y
            
            actual_prob_1_1y = (returns_1y <= sigma_1_1y).sum() / len(returns_1y) * 100
            actual_prob_2_1y = (returns_1y <= sigma_2_1y).sum() / len(returns_1y) * 100
            actual_prob_3_1y = (returns_1y <= sigma_3_1y).sum() / len(returns_1y) * 100
    
        # 시그마 레벨 계산
        sigma_1_5y = mean_5y - std_5y
        sigma_2_5y = mean_5y - 2 * std_5y
        sigma_3_5y = mean_5y - 3 * std_5y
    
        # 실제 발생 확률 계산 (5년)
        actual_prob_1_5y = (returns_5y <= sigma_1_5y).sum() / len(returns_5y) * 100
        actual_prob_2_5y = (returns_5y <= sigma_2_5y).sum() / len(returns_5y) * 100
        actual_prob_3_5y = (returns_5y <= sigma_3_5y).sum() / len(returns_5y) * 100
    
        # 연도별 발생 횟수 계산
        df['연도'] = df.index.year
        yearly_stats = {}
        for year in sorted(df['연도'].unique()):
            year_data = df[df['연도'] == year]
            yearly_stats[year] = {
                '1sigma': (year_data['일일수익률'] <= sigma_1_5y).sum(),
                '2sigma': (year_data['일일수익률'] <= sigma_2_5y).sum(),
                '3sigma': (year_data['일일수익률'] <= sigma_3_5y).sum(),
                'total_days': len(year_data)
            }
    
        return {
            # 5년 데이터
            'mean': mean_5y,
            'std': std_5y,
            '1sigma': sigma_1_5y,
            '2sigma': sigma_2_5y,
            '3sigma': sigma_3_5y,
            'actual_prob_1': actual_prob_1_5y,
            'actual_prob_2': actual_prob_2_5y,
            'actual_prob_3': actual_prob_3_5y,
            # 1년 데이터
            'mean_1y': mean_1y,
            'std_1y': std_1y,
            '1sigma_1y': sigma_1_1y,
            '2sigma_1y': sigma_2_1y,
            '3sigma_1y': sigma_3_1y,
            'actual_prob_1_1y': actual_prob_1_1y,
            'actual_prob_2_1y': actual_prob_2_1y,
            'actual_prob_3_1y': actual_prob_3_1y,
            # 기타
            'last_close': df['종가'].iloc[-1],
            'returns': returns_5y,
            'yearly_stats': yearly_stats
        }
    
    def get_current_price(self, symbol, stock_type='KR'):
        """현재가 가져오기"""
        try:
            if stock_type == 'KR':
                current = stock.get_market_ohlcv_by_ticker(datetime.now().strftime('%Y%m%d'), symbol)
                if not current.empty:
                    return current.loc[symbol, '종가']
            else:
                ticker = yf.Ticker(symbol)
                data = ticker.history(period='1d')
                if not data.empty:
                    return data['Close'].iloc[-1]
            return None
        except:
            return None

# Streamlit 앱 시작
st.title("📉 주식 하락률 모니터링 시스템")
st.markdown("---")

# 사이드바
with st.sidebar:
    st.header("📊 주식 시그마 분석")
    
    st.markdown("---")
    
    # 저장된 종목 불러오기
    st.header("💾 저장된 종목")
    saved_stocks = load_saved_stocks()

    if saved_stocks and not st.session_state.stocks_loaded:
        st.info(f"저장된 종목 {len(saved_stocks)}개 발견")
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
        if st.button("💾 현재 목록 저장", use_container_width=True):
            save_stocks()
            st.success("✅ 저장 완료!")
    
    st.markdown("---")
    
    # 종목 추가 섹션
    st.header("➕ 종목 추가")
    stock_input = st.text_input("종목명 또는 종목코드", placeholder="삼성전자 또는 005930")
    
    if st.button("🔍 검색 및 분석", use_container_width=True):
        if stock_input:
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
            
            # 데이터 분석
            with st.spinner('데이터 분석 중...'):
                df = analyzer.get_stock_data(symbol, stock_type)
                
                if df is not None:
                    stats = analyzer.calculate_sigma_levels(df)
                    
                    # 세션에 저장
                    st.session_state.current_analysis = {
                        'symbol': symbol,
                        'name': name,
                        'type': stock_type,
                        'stats': stats,
                        'df': df
                    }
                    st.success("분석 완료! 아래에서 결과를 확인하세요.")
                else:
                    st.error("데이터를 가져올 수 없습니다.")

# 메인 영역 - 실시간 모니터링을 위로
# 실시간 모니터링 상태 표시
st.header("🚀 실시간 모니터링")
    
# 텔레그램 모니터링 안내
st.info("""
📱 **텔레그램 알림을 원하시면:**
1. 로컬 컴퓨터에서 stock_monitor.py 실행
2. 저장된 종목들이 자동으로 모니터링됩니다
3. 시그마 레벨 도달 시 텔레그램 알림
""")

# 새로고침 버튼만 유지
if st.button("🔄 새로고침", use_container_width=True):
    st.rerun()
    
# 현재가 표시 - 새로운 표 형식
if st.session_state.monitoring_stocks:
    current_prices = []
    analyzer = StockAnalyzer()
    
    for symbol, info in st.session_state.monitoring_stocks.items():
        try:
            # 어제 종가 (last_close가 실제로는 가장 최근 거래일의 종가)
            yesterday_close = info['stats']['last_close']
            
            # 1년 시그마 값들 (퍼센트)
            sigma_1_1y = info['stats'].get('1sigma_1y', info['stats']['1sigma'])
            sigma_2_1y = info['stats'].get('2sigma_1y', info['stats']['2sigma'])
            sigma_3_1y = info['stats'].get('3sigma_1y', info['stats']['3sigma'])
            
            # 시그마 하락시 가격 계산
            price_at_1sigma = yesterday_close * (1 + sigma_1_1y / 100)
            price_at_2sigma = yesterday_close * (1 + sigma_2_1y / 100)
            price_at_3sigma = yesterday_close * (1 + sigma_3_1y / 100)
            
            # 통화 단위 설정
            if info['type'] == 'KR':
                currency = '원'
                price_format = "{:,.0f}"
            else:
                currency = '$'
                price_format = "{:,.2f}"
            
            current_prices.append({
                '종목': f"{info['name']} ({symbol})",
                '어제 종가': f"{currency}{price_format.format(yesterday_close)}",
                '1σ(1년)': f"{sigma_1_1y:.2f}%",
                '1σ 하락시 가격': f"{currency}{price_format.format(price_at_1sigma)}",
                '2σ(1년)': f"{sigma_2_1y:.2f}%",
                '2σ 하락시 가격': f"{currency}{price_format.format(price_at_2sigma)}",
                '3σ(1년)': f"{sigma_3_1y:.2f}%",
                '3σ 하락시 가격': f"{currency}{price_format.format(price_at_3sigma)}"
            })
            
        except Exception as e:
            st.error(f"{symbol} 오류: {str(e)}")
    
    if current_prices:
        df_current = pd.DataFrame(current_prices)
        st.dataframe(df_current, use_container_width=True, hide_index=True)
else:
    st.info("모니터링할 종목을 추가하세요.")

st.markdown("---")

# 분석 결과 표시
col1, col2 = st.columns([2, 1])

with col1:
    # 현재 분석 결과 표시
    if 'current_analysis' in st.session_state:
        analysis = st.session_state.current_analysis
        
        st.header(f"📊 {analysis['name']} ({analysis['symbol']}) 분석 결과")
        
        # 주요 지표
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            current = StockAnalyzer().get_current_price(analysis['symbol'], analysis['type'])
            if current:
                change = ((current - analysis['stats']['last_close']) / analysis['stats']['last_close']) * 100
                st.metric("현재가", f"{current:,.4f}원", f"{change:+.2f}%")
            else:
                st.metric("전일 종가", f"{analysis['stats']['last_close']:,.4f}원")
        with col_b:
            st.metric("평균 수익률", f"{analysis['stats']['mean']:.2f}%")
        with col_c:
            st.metric("표준편차", f"{analysis['stats']['std']:.2f}%")
        with col_d:
            # 현재 변화율과 시그마 레벨 비교
            if current:
                change_pct = ((current - analysis['stats']['last_close']) / analysis['stats']['last_close']) * 100
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
        
        # 시그마 레벨
        st.subheader("🎯 하락 알림 기준")

        # 5년과 1년 비교 탭
        tab_5y, tab_1y = st.tabs(["5년 기준", "1년 기준"])

        with tab_5y:
            sigma_df_5y = pd.DataFrame({
                '레벨': ['1시그마', '2시그마', '3시그마'],
                '하락률': [f"{analysis['stats']['1sigma']:.2f}%", 
                        f"{analysis['stats']['2sigma']:.2f}%", 
                        f"{analysis['stats']['3sigma']:.2f}%"],
                '이론적 확률': ['15.87%', '2.28%', '0.13%'],
                '실제 발생률': [f"{analysis['stats']['actual_prob_1']:.2f}%",
                            f"{analysis['stats']['actual_prob_2']:.2f}%",
                            f"{analysis['stats']['actual_prob_3']:.2f}%"]
            })
            st.dataframe(sigma_df_5y, use_container_width=True, hide_index=True)

        with tab_1y:
            sigma_df_1y = pd.DataFrame({
                '레벨': ['1시그마', '2시그마', '3시그마'],
                '하락률': [f"{analysis['stats']['1sigma_1y']:.2f}%", 
                        f"{analysis['stats']['2sigma_1y']:.2f}%", 
                        f"{analysis['stats']['3sigma_1y']:.2f}%"],
                '이론적 확률': ['15.87%', '2.28%', '0.13%'],
                '실제 발생률': [f"{analysis['stats']['actual_prob_1_1y']:.2f}%",
                            f"{analysis['stats']['actual_prob_2_1y']:.2f}%",
                            f"{analysis['stats']['actual_prob_3_1y']:.2f}%"]
            })
            st.dataframe(sigma_df_1y, use_container_width=True, hide_index=True)
        
        # 연도별 발생 횟수
        st.subheader("📅 연도별 시그마 하락 발생 횟수")
        yearly_data = []
        for year, data in analysis['stats']['yearly_stats'].items():
            yearly_data.append({
                '연도': year,
                '거래일수': data['total_days'],
                '1σ 발생': data['1sigma'],
                '2σ 발생': data['2sigma'],
                '3σ 발생': data['3sigma']
            })
        yearly_df = pd.DataFrame(yearly_data)
        st.dataframe(yearly_df, use_container_width=True, hide_index=True)
        
        # 평균 발생 주기
        col_cycle1, col_cycle2, col_cycle3 = st.columns(3)
        total_days = sum(data['total_days'] for data in analysis['stats']['yearly_stats'].values())
        total_1sigma = sum(data['1sigma'] for data in analysis['stats']['yearly_stats'].values())
        total_2sigma = sum(data['2sigma'] for data in analysis['stats']['yearly_stats'].values())
        total_3sigma = sum(data['3sigma'] for data in analysis['stats']['yearly_stats'].values())
        
        with col_cycle1:
            if total_1sigma > 0:
                st.metric("1σ 평균 주기", f"{total_days/total_1sigma:.1f}일")
        with col_cycle2:
            if total_2sigma > 0:
                st.metric("2σ 평균 주기", f"{total_days/total_2sigma:.1f}일")
        with col_cycle3:
            if total_3sigma > 0:
                st.metric("3σ 평균 주기", f"{total_days/total_3sigma:.1f}일")
            else:
                st.metric("3σ 발생 횟수", f"{total_3sigma}번")
                
        # 수익률 분포 차트
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
        
        # 모니터링 추가 버튼
        if st.button(f"🎯 {analysis['name']} 모니터링 목록에 추가", use_container_width=True, type="primary"):
            st.session_state.monitoring_stocks[analysis['symbol']] = analysis
            save_stocks()  # 자동 저장
            st.success(f"{analysis['name']}이(가) 모니터링 목록에 추가되었습니다!")
            del st.session_state.current_analysis