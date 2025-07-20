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

# 텔레그램 정보 (stock_monitor.py와 동일하게 설정)
TELEGRAM_TOKEN = "88106557069:AAGYmfsihPYhqxPc8x7v7XV-K2ioSabBn9U"
CHAT_ID = "1758796175"

# PID 저장
with open('monitor_pid.txt', 'w') as f:
    f.write(str(os.getpid()))

class AutoMonitor:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.monitoring_stocks = {}
        self.load_stocks()
        
    def load_stocks(self):
        """저장된 종목 자동 로드"""
        try:
            with open('saved_stocks.json', 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            
            print(f"\n📂 {len(saved_data)}개 종목을 자동으로 불러옵니다...")
            
            for symbol, info in saved_data.items():
                print(f"🔄 {info['name']} ({symbol}) 데이터 분석 중...")
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
                    
        except Exception as e:
            print(f"❌ 종목 로드 실패: {e}")
    
    def get_stock_data(self, symbol, stock_type='KR'):
        """5년간 주가 데이터 가져오기"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365*5)
        
        try:
            if stock_type == 'KR':
                df = stock.get_market_ohlcv(start_date.strftime('%Y%m%d'), 
                                           end_date.strftime('%Y%m%d'), 
                                           symbol)
            else:
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start_date, end=end_date)
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                df.columns = ['시가', '고가', '저가', '종가', '거래량']
            return df
        except:
            return None
    
    def calculate_sigma_levels(self, df):
        """시그마 레벨 계산"""
        df['일일수익률'] = df['종가'].pct_change() * 100
        df = df.dropna()
        
        returns = df['일일수익률'].values
        mean_return = df['일일수익률'].mean()
        std_return = df['일일수익률'].std()
        
        return {
            'mean': mean_return,
            'std': std_return,
            '1sigma': mean_return - std_return,
            '2sigma': mean_return - 2 * std_return,
            '3sigma': mean_return - 3 * std_return,
            'last_close': df['종가'].iloc[-1]
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
    
    async def send_telegram_message(self, message):
        """텔레그램 메시지 전송"""
        try:
            await self.bot.send_message(chat_id=CHAT_ID, text=message)
            print(f"✅ 텔레그램 알림 전송 완료")
        except Exception as e:
            print(f"❌ 텔레그램 전송 실패: {e}")
    
    async def monitor_all_stocks(self):
        """모든 종목 자동 모니터링"""
        print(f"\n📊 {len(self.monitoring_stocks)}개 종목 자동 모니터링 시작...")
        
        # 시작 알림
        await self.send_telegram_message(f"🚀 모니터링이 시작되었습니다!\n종목: {', '.join([info['name'] for info in self.monitoring_stocks.values()])}")
        
        while True:
            try:
                # saved_stocks.json 파일 변경 확인
                self.check_stock_updates()
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 가격 체크 중...")
                alerts = []
                
                for symbol, info in self.monitoring_stocks.items():
                    current_price = self.get_current_price(symbol, info['type'])
                    
                    if current_price:
                        yesterday_close = info['stats']['last_close']
                        change_percent = ((current_price - yesterday_close) / yesterday_close) * 100
                        
                        # 시그마 레벨 체크
                        alert_level = None
                        if change_percent <= info['stats']['3sigma']:
                            alert_level = '3σ (1년)'
                        elif change_percent <= info['stats']['2sigma']:
                            alert_level = '2σ (1년)'
                        elif change_percent <= info['stats']['1sigma']:
                            alert_level = '1σ (1년)'
                        
                        if alert_level and (current_price != info['last_alert_price'] or 
                                          alert_level != info['last_alert_level']):
                            alert_msg = f"📉 {info['name']}({symbol})\n"
                            alert_msg += f"현재가: {current_price:,.0f}원\n"
                            alert_msg += f"변화율: {change_percent:.2f}%\n"
                            alert_msg += f"레벨: {alert_level}"
                            alerts.append(alert_msg)
                            
                            info['last_alert_price'] = current_price
                            info['last_alert_level'] = alert_level
                
                if alerts:
                    full_message = "🚨 주식 하락 알림 🚨\n\n" + "\n\n".join(alerts)
                    await self.send_telegram_message(full_message)
                
                await asyncio.sleep(300)  # 5분 대기
                
            except KeyboardInterrupt:
                await self.send_telegram_message("⏹️ 모니터링이 중지되었습니다.")
                break
            except Exception as e:
                print(f"오류 발생: {e}")
                await asyncio.sleep(60)
    
    def check_stock_updates(self):
        """saved_stocks.json 파일 변경 확인 및 업데이트"""
        try:
            with open('saved_stocks.json', 'r', encoding='utf-8') as f:
                current_saved = json.load(f)
            
            # 새로운 종목 추가
            for symbol, info in current_saved.items():
                if symbol not in self.monitoring_stocks:
                    print(f"\n🆕 새 종목 발견: {info['name']} ({symbol})")
                    df = self.get_stock_data(symbol, info['type'])
                    if df is not None:
                        stats = self.calculate_sigma_levels(df)
                        self.monitoring_stocks[symbol] = {
                            'name': info['name'],
                            'type': info['type'],
                            'stats': stats,
                            'last_alert_price': None,
                            'last_alert_level': None
                        }
            
            # 제거된 종목 삭제
            to_remove = []
            for symbol in self.monitoring_stocks:
                if symbol not in current_saved:
                    to_remove.append(symbol)
            
            for symbol in to_remove:
                print(f"\n🗑️ 종목 제거: {self.monitoring_stocks[symbol]['name']} ({symbol})")
                del self.monitoring_stocks[symbol]
                
        except Exception as e:
            print(f"업데이트 확인 중 오류: {e}")

async def main():
    monitor = AutoMonitor()
    await monitor.monitor_all_stocks()

if __name__ == "__main__":
    # PID 파일 정리
    try:
        asyncio.run(main())
    finally:
        if os.path.exists('monitor_pid.txt'):
            os.remove('monitor_pid.txt')
