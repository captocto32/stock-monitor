import yfinance as yf
from pykrx import stock
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import asyncio
from telegram import Bot
import json
import os
import warnings
warnings.filterwarnings('ignore')

# ===== 여기에 본인의 정보를 입력하세요 =====
TELEGRAM_TOKEN = "8106557069:AAGYmfsihPYhqxPc8x7v7XV-K2ioSabBn9U"
CHAT_ID = "1758796175"
# ==========================================

class StockMonitor:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.monitoring_stocks = {}  # 여러 종목 저장
        self.save_file = 'saved_stocks.json'  # 저장 파일명
        
    async def send_telegram_message(self, message):
        """텔레그램 메시지 전송"""
        try:
            await self.bot.send_message(chat_id=CHAT_ID, text=message)
            print(f"✅ 텔레그램 알림 전송 완료")
        except Exception as e:
            print(f"❌ 텔레그램 전송 실패: {e}")
    
    def search_korean_stock(self, query):
        """한국 주식 검색 (종목명 또는 코드)"""
        try:
            # 숫자로만 이루어져 있으면 종목코드로 간주
            if query.isdigit() and len(query) == 6:
                name = stock.get_market_ticker_name(query)
                if name:
                    return query, name
            else:
                # 종목명으로 검색
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
                # 한국 주식
                df = stock.get_market_ohlcv(start_date.strftime('%Y%m%d'), 
                                           end_date.strftime('%Y%m%d'), 
                                           symbol)
                if df.empty:
                    return None
            else:
                # 미국 주식
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start_date, end=end_date)
                if df.empty:
                    return None
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                df.columns = ['시가', '고가', '저가', '종가', '거래량']
            
            return df
        except Exception as e:
            print(f"데이터 가져오기 실패: {e}")
            return None
    
    def calculate_sigma_levels(self, df):
        """표준편차 및 시그마 레벨 계산"""
        # 일일 수익률 계산 (전일 종가 대비)
        df['일일수익률'] = df['종가'].pct_change() * 100
        df = df.dropna()
        
        # 통계 계산
        returns = df['일일수익률'].values
        mean_return = df['일일수익률'].mean()
        std_return = df['일일수익률'].std()
        
        # 시그마 레벨 (하락 기준이므로 음수)
        sigma_1 = mean_return - std_return
        sigma_2 = mean_return - 2 * std_return
        sigma_3 = mean_return - 3 * std_return
        
        # 실제 발생 확률 계산
        actual_prob_1 = (returns <= sigma_1).sum() / len(returns) * 100
        actual_prob_2 = (returns <= sigma_2).sum() / len(returns) * 100
        actual_prob_3 = (returns <= sigma_3).sum() / len(returns) * 100
        
        # 연도별 발생 횟수 계산
        df['연도'] = df.index.year
        yearly_stats = {}
        for year in sorted(df['연도'].unique()):
            year_data = df[df['연도'] == year]
            yearly_stats[year] = {
                '1sigma': (year_data['일일수익률'] <= sigma_1).sum(),
                '2sigma': (year_data['일일수익률'] <= sigma_2).sum(),
                '3sigma': (year_data['일일수익률'] <= sigma_3).sum(),
                'total_days': len(year_data)
            }
        
        return {
            'mean': mean_return,
            'std': std_return,
            '1sigma': sigma_1,
            '2sigma': sigma_2,
            '3sigma': sigma_3,
            'actual_prob_1': actual_prob_1,
            'actual_prob_2': actual_prob_2,
            'actual_prob_3': actual_prob_3,
            'last_close': df['종가'].iloc[-1],
            'yearly_stats': yearly_stats
        }
    
    def display_analysis(self, name, symbol, stats):
        """분석 결과 출력"""
        print("\n" + "="*50)
        print(f"종목: {name} ({symbol})")
        
        # 현재가 정보 추가
        stock_type = 'KR' if symbol.isdigit() else 'US'
        current_price = self.get_current_price(symbol, stock_type)
        if current_price:
            change = ((current_price - stats['last_close']) / stats['last_close']) * 100
            print(f"현재가: {current_price:,.0f}원 ({change:+.2f}%)")
        print(f"전일 종가: {stats['last_close']:,.0f}원")
        
        print(f"\n[5년간 일일 수익률 통계]")
        print(f"평균 수익률: {stats['mean']:.2f}%")
        print(f"표준편차: {stats['std']:.2f}%")
        print(f"\n[하락 알림 기준 및 실제 발생 확률]")
        print(f"1시그마: {stats['1sigma']:.2f}% (이론: 15.87% / 실제: {stats['actual_prob_1']:.2f}%)")
        print(f"2시그마: {stats['2sigma']:.2f}% (이론: 2.28% / 실제: {stats['actual_prob_2']:.2f}%)")
        print(f"3시그마: {stats['3sigma']:.2f}% (이론: 0.13% / 실제: {stats['actual_prob_3']:.2f}%)")
        
        # 연도별 발생 횟수 표시
        print(f"\n[연도별 시그마 하락 발생 횟수]")
        print(f"{'연도':>6} | {'거래일':>6} | {'1σ':>5} | {'2σ':>5} | {'3σ':>5}")
        print("-" * 40)
        for year, data in stats['yearly_stats'].items():
            print(f"{year:>6} | {data['total_days']:>6} | {data['1sigma']:>5} | {data['2sigma']:>5} | {data['3sigma']:>5}")
        
        # 평균 발생 주기 계산
        total_days = sum(data['total_days'] for data in stats['yearly_stats'].values())
        total_1sigma = sum(data['1sigma'] for data in stats['yearly_stats'].values())
        total_2sigma = sum(data['2sigma'] for data in stats['yearly_stats'].values())
        total_3sigma = sum(data['3sigma'] for data in stats['yearly_stats'].values())
        
        print("-" * 40)
        print(f"\n[평균 발생 주기]")
        if total_1sigma > 0:
            print(f"1시그마: 약 {total_days/total_1sigma:.1f}일에 한 번")
        if total_2sigma > 0:
            print(f"2시그마: 약 {total_days/total_2sigma:.1f}일에 한 번")
        if total_3sigma > 0:
            print(f"3시그마: 약 {total_days/total_3sigma:.1f}일에 한 번")
        else:
            print(f"3시그마: 5년간 {total_3sigma}번 발생")
        
        print("="*50)
    
    def add_stock(self, symbol, name, stock_type, stats):
        """모니터링 목록에 종목 추가"""
        self.monitoring_stocks[symbol] = {
            'name': name,
            'type': stock_type,
            'stats': stats,
            'last_alert_price': None,
            'last_alert_level': None
        }
        print(f"\n✅ {name}({symbol})이(가) 모니터링 목록에 추가되었습니다.")
        self.save_stocks()  # 자동 저장
    
    def save_stocks(self):
        """모니터링 종목 목록을 파일로 저장"""
        save_data = {}
        for symbol, info in self.monitoring_stocks.items():
            save_data[symbol] = {
                'name': info['name'],
                'type': info['type']
            }
        
        with open(self.save_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        print("💾 종목 목록이 자동 저장되었습니다.")
    
    def load_stocks(self):
        """저장된 종목 목록 불러오기"""
        if not os.path.exists(self.save_file):
            return False
        
        try:
            with open(self.save_file, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            
            if not saved_data:
                return False
            
            print(f"\n📂 저장된 종목 {len(saved_data)}개를 발견했습니다:")
            for symbol, info in saved_data.items():
                print(f"   - {info['name']} ({symbol})")
            
            load = input("\n이 종목들을 불러올까요? (y/n): ")
            if load.lower() == 'y':
                print("\n불러오는 중...")
                for symbol, info in saved_data.items():
                    print(f"\n🔄 {info['name']} ({symbol}) 데이터 분석 중...")
                    df = self.get_stock_data(symbol, info['type'])
                    if df is not None and not df.empty:
                        stats = self.calculate_sigma_levels(df)
                        self.monitoring_stocks[symbol] = {
                            'name': info['name'],
                            'type': info['type'],
                            'stats': stats,
                            'last_alert_price': None,
                            'last_alert_level': None
                        }
                        print(f"✅ {info['name']} 로드 완료")
                    else:
                        print(f"❌ {info['name']} 데이터 로드 실패")
                
                print(f"\n✅ 총 {len(self.monitoring_stocks)}개 종목이 로드되었습니다.")
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ 저장된 데이터 로드 중 오류: {e}")
            return False
    
    def display_monitoring_list(self):
        """현재 모니터링 중인 종목 목록 표시"""
        if not self.monitoring_stocks:
            print("\n📋 모니터링 중인 종목이 없습니다.")
        else:
            print("\n📋 모니터링 중인 종목 목록:")
            print("-" * 60)
            for i, (symbol, info) in enumerate(self.monitoring_stocks.items(), 1):
                print(f"{i}. {info['name']} ({symbol}) - {info['type']} | "
                      f"1σ: {info['stats']['1sigma']:.1f}% | "
                      f"2σ: {info['stats']['2sigma']:.1f}% | "
                      f"3σ: {info['stats']['3sigma']:.1f}%")
            print("-" * 60)
    
    def remove_stock(self, symbol):
        """모니터링 목록에서 종목 제거"""
        if symbol in self.monitoring_stocks:
            name = self.monitoring_stocks[symbol]['name']
            del self.monitoring_stocks[symbol]
            print(f"\n✅ {name}({symbol})이(가) 모니터링 목록에서 제거되었습니다.")
            self.save_stocks()  # 자동 저장
        else:
            print(f"\n❌ {symbol}은(는) 모니터링 목록에 없습니다.")
    
    def get_current_price(self, symbol, stock_type='KR'):
        """현재가 가져오기"""
        try:
            if stock_type == 'KR':
                # 한국 주식 (20분 지연)
                current = stock.get_market_ohlcv_by_ticker(datetime.now().strftime('%Y%m%d'), symbol)
                if not current.empty:
                    return current.loc[symbol, '종가']
            else:
                # 미국 주식
                ticker = yf.Ticker(symbol)
                data = ticker.history(period='1d')
                if not data.empty:
                    return data['Close'].iloc[-1]
            return None
        except:
            return None
    
    async def monitor_all_stocks(self):
        """모든 종목 동시 모니터링"""
        print(f"\n📊 {len(self.monitoring_stocks)}개 종목 모니터링 시작...")
        print("5분마다 모든 종목의 가격을 체크합니다. 중지하려면 Ctrl+C를 누르세요.\n")
        
        while True:
            try:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 가격 체크 중...")
                print("-" * 80)
                
                alerts = []  # 알림 메시지 모음
                
                for symbol, info in self.monitoring_stocks.items():
                    # 현재가 가져오기
                    current_price = self.get_current_price(symbol, info['type'])
                    
                    if current_price:
                        # 변화율 계산
                        yesterday_close = info['stats']['last_close']
                        change_percent = ((current_price - yesterday_close) / yesterday_close) * 100
                        
                        # 현재 상태 출력
                        status = f"{info['name']}({symbol}): {current_price:,.0f}원 ({change_percent:+.2f}%)"
                        
                        # 시그마 레벨 체크
                        alert_level = None
                        if change_percent <= info['stats']['3sigma']:
                            alert_level = '3σ'
                            status += " 🚨🚨🚨 3시그마 돌파!"
                        elif change_percent <= info['stats']['2sigma']:
                            alert_level = '2σ'
                            status += " 🚨🚨 2시그마 돌파!"
                        elif change_percent <= info['stats']['1sigma']:
                            alert_level = '1σ'
                            status += " 🚨 1시그마 돌파!"
                        
                        print(status)
                        
                        # 알림 조건 확인 (같은 레벨에서 중복 알림 방지)
                        if alert_level and (current_price != info['last_alert_price'] or 
                                          alert_level != info['last_alert_level']):
                            alert_msg = f"📉 {info['name']}({symbol})\n"
                            alert_msg += f"현재가: {current_price:,.0f}원\n"
                            alert_msg += f"변화율: {change_percent:.2f}%\n"
                            alert_msg += f"레벨: {alert_level} ({info['stats'][alert_level.lower()]:.2f}%)"
                            alerts.append(alert_msg)
                            
                            # 알림 정보 업데이트
                            info['last_alert_price'] = current_price
                            info['last_alert_level'] = alert_level
                    else:
                        print(f"{info['name']}({symbol}): 가격 정보 없음")
                
                print("-" * 80)
                
                # 텔레그램 알림 전송
                if alerts:
                    full_message = "🚨 주식 하락 알림 🚨\n\n" + "\n\n".join(alerts)
                    await self.send_telegram_message(full_message)
                
                # 5분 대기
                await asyncio.sleep(300)
                
            except KeyboardInterrupt:
                print("\n\n모니터링 중지됨")
                break
            except Exception as e:
                print(f"\n오류 발생: {e}")
                await asyncio.sleep(60)  # 오류 시 1분 후 재시도

async def main():
    monitor = StockMonitor()
    
    print("📈 다중 주식 하락률 모니터링 프로그램")
    print("="*50)
    
    # 저장된 종목 자동 로드
    monitor.load_stocks()
    
    while True:
        print("\n메뉴:")
        print("1. 종목 추가")
        print("2. 종목 제거")
        print("3. 모니터링 시작")
        print("4. 현재 목록 보기")
        print("5. 저장된 종목 다시 불러오기")
        print("6. 종료")
        
        choice = input("\n선택하세요 (1-6): ").strip()
        
        if choice == '1':
            # 종목 추가
            query = input("\n종목명 또는 종목코드를 입력하세요: ").strip()
            
            # 한국 주식 검색
            kr_code, kr_name = monitor.search_korean_stock(query)
            
            if kr_code:
                # 한국 주식 발견
                print(f"\n✅ 한국 주식 발견: {kr_name} ({kr_code})")
                symbol, name, stock_type = kr_code, kr_name, 'KR'
            else:
                # 미국 주식으로 시도
                symbol = query.upper()
                print(f"\n🔍 미국 주식 {symbol} 검색 중...")
                name, stock_type = symbol, 'US'
            
            # 데이터 가져오기
            print("📊 5년간 데이터 분석 중...")
            df = monitor.get_stock_data(symbol, stock_type)
            
            if df is None or df.empty:
                print("❌ 데이터를 가져올 수 없습니다.")
                continue
            
            # 시그마 레벨 계산
            stats = monitor.calculate_sigma_levels(df)
            
            # 결과 표시
            monitor.display_analysis(name, symbol, stats)
            
            # 추가 확인
            add = input("\n이 종목을 모니터링 목록에 추가하시겠습니까? (y/n): ")
            if add.lower() == 'y':
                monitor.add_stock(symbol, name, stock_type, stats)
        
        elif choice == '2':
            # 종목 제거
            monitor.display_monitoring_list()
            if monitor.monitoring_stocks:
                symbol = input("\n제거할 종목 코드를 입력하세요: ").strip().upper()
                monitor.remove_stock(symbol)
        
        elif choice == '3':
            # 모니터링 시작
            if not monitor.monitoring_stocks:
                print("\n❌ 모니터링할 종목이 없습니다. 먼저 종목을 추가하세요.")
            else:
                monitor.display_monitoring_list()
                await monitor.monitor_all_stocks()
        
        elif choice == '4':
            # 현재 목록 보기
            monitor.display_monitoring_list()
        
        elif choice == '5':
            # 저장된 종목 다시 불러오기
            monitor.monitoring_stocks.clear()
            if monitor.load_stocks():
                monitor.display_monitoring_list()
            else:
                print("\n저장된 종목이 없거나 불러오기를 취소했습니다.")
        
        elif choice == '6':
            # 종료
            print("\n프로그램을 종료합니다. 안녕히 가세요! 👋")
            break
        
        else:
            print("\n❌ 잘못된 선택입니다. 1-6 중에서 선택하세요.")

if __name__ == "__main__":
    # 텔레그램 봇 토큰 확인
    if TELEGRAM_TOKEN == "여기에_봇_토큰_입력":
        print("⚠️  주의: stock_monitor.py 파일을 열어서 TELEGRAM_TOKEN을 입력해주세요!")
        print("   13번째 줄의 '여기에_봇_토큰_입력' 부분을 실제 봇 토큰으로 변경하세요.")
    else:
        asyncio.run(main())