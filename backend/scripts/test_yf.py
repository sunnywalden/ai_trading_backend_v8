import yfinance as yf
import json

def test():
    ticker = yf.Ticker("MSFT")
    info = ticker.info
    print(f"Sector: {info.get('sector')}")
    print(f"Industry: {info.get('industry')}")
    print(f"Beta: {info.get('beta')}")
    # print(json.dumps(info, indent=2))

if __name__ == "__main__":
    test()
