# Tiger Open API 集成说明

本项目使用老虎证券官方 Python SDK (`tigeropen`) 实现期权交易和风险管理功能。

## 官方文档

- **开放平台首页**：https://quant.itigerup.com/openapi/
- **Python SDK 文档**：https://quant.itigerup.com/openapi/zh/python/quickStart/fullFunction.html
- **准备工作**：https://quant.itigerup.com/openapi/zh/python/quickStart/prepare.html
- **API 参考**：https://quant.itigerup.com/openapi/zh/python/

## SDK 安装

```bash
pip install tigeropen --upgrade
```

## 快速配置

### 1. 注册老虎账户

访问 [老虎证券](https://www.itiger.com/) 注册账户，开通模拟盘或真实账户。

### 2. 申请开发者权限

1. 登录 [老虎开放平台](https://quant.itigerup.com/)
2. 创建应用并获取 **tiger_id**
3. 记录您的账户号码

### 3. 生成 RSA 密钥对

```bash
# 生成私钥（1024位或2048位）
openssl genrsa -out private_key.pem 1024

# 生成公钥
openssl rsa -in private_key.pem -pubout -out public_key.pem

# 查看公钥内容
cat public_key.pem
```

### 4. 上传公钥

1. 在开放平台进入"密钥管理"
2. 上传 `public_key.pem` 的内容
3. 保存 `private_key.pem` 到安全位置

### 5. 配置项目

在项目根目录创建 `.env` 文件：

```env
TIGER_ACCOUNT=your_account_number
TIGER_PRIVATE_KEY_PATH=/path/to/private_key.pem
TIGER_ID=your_tiger_id
```

## 项目中的使用

### 期权客户端 (TigerOptionClient)

负责获取持仓和 Greeks 数据：

```python
from tigeropen.tiger_open_config import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient

# 初始化配置
client_config = get_client_config(
    private_key_path="/path/to/private_key.pem",
    tiger_id="your_tiger_id",
    account="your_account"
)

# 创建客户端
trade_client = TradeClient(client_config)
quote_client = QuoteClient(client_config)

# 获取股票持仓
positions = trade_client.get_positions(
    sec_type=SecurityType.STK,
    market=Market.US
)

# 获取期权持仓
option_positions = trade_client.get_positions(
    sec_type=SecurityType.OPT,
    market=Market.US
)

# 获取期权 Greeks
option_briefs = quote_client.get_option_briefs(symbols)
```

### 历史成交客户端 (TigerTradeHistoryClient)

负责获取历史成交记录用于行为分析：

```python
# 获取历史成交订单
filled_orders = trade_client.get_filled_orders(
    account=account_id,
    sec_type=SecurityType.STK,
    market=Market.US,
    start_time=start_timestamp,
    end_time=end_timestamp
)
```

## 常见问题

### 1. 私钥文件权限错误

```bash
# 设置正确的文件权限
chmod 600 private_key.pem
```

### 2. SDK 导入错误

确保已安装最新版本：

```bash
pip install tigeropen --upgrade
```

### 3. 连接超时

检查网络连接，可能需要配置代理或使用海外服务器。

### 4. 行情权限不足

某些行情数据需要额外申请权限，访问开放平台"权限管理"查看。

## 支持的市场

- **美股 (US)**：股票、ETF、期权
- **港股 (HK)**：股票、ETF、期权
- **A股 (CN)**：股票（部分支持）

本项目默认使用美股市场，如需支持其他市场，修改相关代码中的 `Market` 参数。

## 费率和限制

- **行情接口**：有调用频率限制（通常 1秒/次）
- **交易接口**：根据账户类型有不同限制
- **历史数据**：可查询时间范围有限制

详细费率和限制请参考 [官方文档](https://quant.itigerup.com/openapi/zh/python/)。

## 安全提示

1. **私钥安全**：
   - 不要将私钥提交到代码仓库
   - 使用 `.gitignore` 排除 `*.pem` 文件
   - 定期更换密钥

2. **测试先行**：
   - 先使用模拟盘测试
   - 确认功能正常后再连接真实账户
   - 设置合理的风险限额

3. **监控告警**：
   - 实时监控系统运行状态
   - 设置异常情况告警
   - 定期检查持仓和风险指标

## 参考资源

- [完整使用示例](https://quant.itigerup.com/openapi/zh/python/quickStart/fullFunction.html)
- [基本功能示例](https://quant.itigerup.com/openapi/zh/python/quickStart/basicFunction.html)
- [错误处理](https://quant.itigerup.com/openapi/zh/python/errorHandle/overview.html)
- [常见问题](https://quant.itigerup.com/openapi/zh/python/faq.html)
