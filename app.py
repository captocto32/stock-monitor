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
            st.write(f"Debug - Symbol: {symbol}, Type: {stock_type}")
            st.write(f"Debug - Error type: {type(e).__name__}")
            st.write(f"Debug - Error details: {str(e)}")
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
                '1sigma': ((year_data['일일수익률'] <= sigma_1_5y) & (year_data['일일수익률'] > sigma_2_5y)).sum(),
                '2sigma': ((year_data['일일수익률'] <= sigma_2_5y) & (year_data['일일수익률'] > sigma_3_5y)).sum(),
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
st.title("🍣 주식 하락률 모니터링 시스템")
st.markdown("---")

# 사이드바
with st.sidebar:
    st.header("🦁 주식 시그마 분석")
    
    st.markdown("---")
    
    # 저장된 종목 불러오기
    st.header("🍚 저장된 종목")
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
    
    # 검색 히스토리 초기화
    if 'search_history' not in st.session_state:
        st.session_state.search_history = []
    
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
                st.write(f"디버그: kr_code={kr_code}, kr_name={kr_name}")  # 추가
                
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
                    
                    # 세션에 저장 (강제로 덮어쓰기)
                    st.session_state.current_analysis = {
                        'symbol': symbol,
                        'name': name,
                        'type': stock_type,
                        'stats': stats,
                        'df': df
                    }

                    # 검색 히스토리에 추가
                    history_item = f"{name} ({symbol})"
                    if history_item not in st.session_state.search_history:
                        st.session_state.search_history.insert(0, history_item)
                        # 최대 10개까지만 유지
                        st.session_state.search_history = st.session_state.search_history[:10]
                    
                    # 디버깅용 - 히스토리 확인
                    st.write(f"현재 검색 히스토리: {st.session_state.search_history}")

                    st.success("분석 완료! 아래에서 결과를 확인하세요.")
                    st.rerun()
                else:
                    st.error("데이터를 가져올 수 없습니다.")

    # 검색 히스토리
    if 'search_history' in st.session_state and st.session_state.search_history:
        st.markdown("---")
        st.subheader("🕐 최근 검색")
        for i, item in enumerate(st.session_state.search_history):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{item}**")  # 굵은 글씨로 표시
            with col2:
                if st.button("↻", key=f"history_{i}_{item}", help="다시 검색"):
                    # 종목명과 심볼 추출
                    parts = item.rsplit(' (', 1)  # 마지막 괄호 기준으로 분리
                    if len(parts) == 2:
                        name = parts[0]
                        symbol = parts[1].rstrip(')')
                    else:
                        name = symbol = item
                    
                    # 직접 분석 실행
                    analyzer = StockAnalyzer()
                    
                    # 종목 타입 확인 (6자리면 한국, 아니면 미국)
                    if len(symbol) == 6 and symbol.isdigit():
                        stock_type = 'KR'
                        name = item.split(' (')[0]
                    else:
                        stock_type = 'US'
                        name = symbol
                    
                    # 데이터 분석
                    df = analyzer.get_stock_data(symbol, stock_type)
                    if df is not None:
                        stats = analyzer.calculate_sigma_levels(df)
                        st.session_state.current_analysis = {
                            'symbol': symbol,
                            'name': name,
                            'type': stock_type,
                            'stats': stats,
                            'df': df
                        }
                        st.rerun()

# 메인 영역 - 실시간 모니터링을 위로
# 실시간 모니터링 상태 표시
st.header("🍙 실시간 모니터링")
    
# 텔레그램 모니터링 안내
st.info("""
📱 **텔레그램 알림**
1. 로컬 컴퓨터에서 stock_monitor.py 실행 시 저장된 종목들 자동으로 모니터링 시작
2. 시그마 레벨 도달 시 텔레그램 알림
""")

# 새로고침 버튼만 유지
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
            for symbol, info in kr_stocks.items():
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
                    currency = '원'
                    price_format = "{:,.0f}"
                    
                    current_prices_kr.append({
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
            
            if current_prices_kr:
                # DataFrame 생성 및 정렬
                df_current_kr = pd.DataFrame(current_prices_kr)
                df_current_kr['정렬키'] = df_current_kr['종목'].apply(lambda x: x.split('(')[0].strip())
                df_current_kr = df_current_kr.sort_values(by='정렬키').drop(columns=['정렬키']).reset_index(drop=True)
                
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
                    
                    if 'current_analysis' not in st.session_state or st.session_state.current_analysis.get('symbol') != symbol:
                        for sym, info in st.session_state.monitoring_stocks.items():
                            if sym == symbol:
                                st.session_state.current_analysis = {
                                    'symbol': sym,
                                    'name': info['name'],
                                    'type': info['type'],
                                    'stats': info['stats'],
                                    'df': info['df']
                                }
                                st.rerun()
                                break
        else:
            st.info("모니터링 중인 한국 주식이 없습니다.")
    
    # 미국 주식 탭
    with tab_us:
        if us_stocks:
            current_prices_us = []
            for symbol, info in us_stocks.items():
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
                    currency = '$'
                    price_format = "{:,.2f}"
                    
                    current_prices_us.append({
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
            
            if current_prices_us:
                # DataFrame 생성 및 정렬
                df_current_us = pd.DataFrame(current_prices_us)
                df_current_us['정렬키'] = df_current_us['종목'].apply(lambda x: x.split('(')[0].strip())
                df_current_us['is_english'] = df_current_us['정렬키'].apply(lambda x: x[0].encode().isalpha())
                df_current_us = df_current_us.sort_values(by=['is_english', '정렬키'], ascending=[False, True])
                df_current_us = df_current_us.drop(columns=['정렬키', 'is_english']).reset_index(drop=True)
                
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
                    
                    if 'current_analysis' not in st.session_state or st.session_state.current_analysis.get('symbol') != symbol:
                        for sym, info in st.session_state.monitoring_stocks.items():
                            if sym == symbol:
                                st.session_state.current_analysis = {
                                    'symbol': sym,
                                    'name': info['name'],
                                    'type': info['type'],
                                    'stats': info['stats'],
                                    'df': info['df']
                                }
                                st.rerun()
                                break
        else:
            st.info("모니터링 중인 미국 주식이 없습니다.")

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

            # 시그마 하락시 가격 표시
        st.markdown("---")
        st.subheader("💰 시그마 하락시 목표 가격")
        
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
            currency = '원'
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
        
        # 디버깅 정보 추가
        with st.expander("🔍 시그마 계산 확인"):
            st.write(f"**5년 기준 시그마 값:**")
            st.write(f"- 1σ: {analysis['stats']['1sigma']:.2f}%")
            st.write(f"- 2σ: {analysis['stats']['2sigma']:.2f}%")
            st.write(f"- 3σ: {analysis['stats']['3sigma']:.2f}%")
            st.write(f"\n**구간별 정의:**")
            st.write(f"- 1σ 구간: {analysis['stats']['2sigma']:.2f}% < 하락률 ≤ {analysis['stats']['1sigma']:.2f}%")
            st.write(f"- 2σ 구간: {analysis['stats']['3sigma']:.2f}% < 하락률 ≤ {analysis['stats']['2sigma']:.2f}%")
            st.write(f"- 3σ 구간: 하락률 ≤ {analysis['stats']['3sigma']:.2f}%")

        # 최근 발생일 및 연속 발생 정보
        df_analysis = analysis['df'].copy()
        df_analysis['일일수익률'] = df_analysis['종가'].pct_change() * 100
        
        # 각 시그마 구간별 발생일 찾기
        sigma_1_dates = df_analysis[(df_analysis['일일수익률'] <= analysis['stats']['1sigma']) & 
                                    (df_analysis['일일수익률'] > analysis['stats']['2sigma'])].index
        sigma_2_dates = df_analysis[(df_analysis['일일수익률'] <= analysis['stats']['2sigma']) & 
                                    (df_analysis['일일수익률'] > analysis['stats']['3sigma'])].index
        sigma_3_dates = df_analysis[df_analysis['일일수익률'] <= analysis['stats']['3sigma']].index
        
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
            tab1, tab2, tab3 = st.tabs(["2σ 구간 발생일", "3σ 이하 발생일", "극단적 하락 TOP 10"])
            
            with tab1:
                if len(sigma_2_dates) > 0:
                    recent_2sigma = []
                    for date in sigma_2_dates[-20:]:  # 최근 20개
                        return_pct = df_analysis.loc[date, '일일수익률']
                        recent_2sigma.append({
                            '날짜': date.strftime('%Y-%m-%d'),
                            '수익률': f"{return_pct:.2f}%"
                        })
                    st.dataframe(pd.DataFrame(recent_2sigma), use_container_width=True, hide_index=True)
                    st.caption(f"2σ 구간: {analysis['stats']['3sigma']:.2f}% < 하락률 ≤ {analysis['stats']['2sigma']:.2f}%")
                else:
                    st.info("2σ 구간 하락 발생 이력이 없습니다.")
                    
            with tab2:
                if len(sigma_3_dates) > 0:
                    recent_3sigma = []
                    for date in sigma_3_dates:  # 3σ는 모두 표시
                        return_pct = df_analysis.loc[date, '일일수익률']
                        recent_3sigma.append({
                            '날짜': date.strftime('%Y-%m-%d'),
                            '수익률': f"{return_pct:.2f}%"
                        })
                    st.dataframe(pd.DataFrame(recent_3sigma), use_container_width=True, hide_index=True)
                    st.caption(f"3σ 이하: 하락률 ≤ {analysis['stats']['3sigma']:.2f}%")
                else:
                    st.info("3σ 이하 하락 발생 이력이 없습니다.")
                    
            with tab3:
                # 최악의 하락일 TOP 10
                worst_days = df_analysis.nsmallest(10, '일일수익률')[['일일수익률']].copy()
                worst_days['날짜'] = worst_days.index.strftime('%Y-%m-%d')
                worst_days['수익률'] = worst_days['일일수익률'].apply(lambda x: f"{x:.2f}%")
                st.dataframe(worst_days[['날짜', '수익률']], use_container_width=True, hide_index=True)
                
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
            # 디버깅용
            st.write(f"추가 중: {analysis['symbol']} / {analysis['name']} / {analysis['type']}")
            
            st.session_state.monitoring_stocks[analysis['symbol']] = analysis
            save_stocks()  # 자동 저장
            st.success(f"{analysis['name']}이(가) 모니터링 목록에 추가되었습니다!")
            
            # 저장 확인
            st.write(f"현재 모니터링 종목: {list(st.session_state.monitoring_stocks.keys())}")
            
            del st.session_state.current_analysis