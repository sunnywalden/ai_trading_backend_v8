# 🚀 快速启动指南

## 5分钟快速体验

### 1. 克隆项目（如果还没有）

```bash
git clone <your-repo-url>
cd ai_trading_backend_v8
```

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 3. 配置环境（选择一种方式）

#### 方式 A：使用 Dummy 客户端（推荐新手）

不需要 Tiger API，直接使用测试模式：

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env，确保以下配置为空（使用默认值）
# TIGER_PRIVATE_KEY_PATH=
# TIGER_ID=
```

#### 方式 B：连接真实 Tiger API

如果您已有 Tiger 账户和 API 权限：

```bash
# 1. 复制配置模板
cp .env.example .env

# 2. 生成密钥（如果还没有）
openssl genrsa -out private_key.pem 1024
openssl rsa -in private_key.pem -pubout -out public_key.pem

# 3. 上传公钥到 https://quant.itigerup.com

# 4. 编辑 .env，填入：
# TIGER_PRIVATE_KEY_PATH=/path/to/private_key.pem
# TIGER_ID=your_tiger_id
# TIGER_ACCOUNT=your_account
```

详细配置请参考：[TIGER_API_GUIDE.md](TIGER_API_GUIDE.md)

### 4. 测试配置（可选但推荐）

```bash
# 返回项目根目录
cd ..

# 运行测试脚本
python test_tiger_api.py
```

预期输出：
- ✅ 配置检查完成
- ✅ 期权客户端测试通过
- ✅ 历史成交客户端测试通过

### 5. 启动服务

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务启动后访问：
- **API 文档**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/health

## 🎯 核心功能测试

### 1. 健康检查

```bash
curl http://localhost:8000/health
```

预期返回：
```json
{
  "status": "ok",
  "mode": "DRY_RUN"
}
```

### 2. 获取系统状态

```bash
curl http://localhost:8000/ai/state
```

返回当前风险状态、Greeks 敞口和行为画像。

### 3. 手动触发对冲

```bash
curl -X POST http://localhost:8000/run-auto-hedge-once
```

系统会评估当前风险并生成对冲建议。

### 4. AI 决策建议

```bash
curl -X POST http://localhost:8000/ai/advice \
  -H "Content-Type: application/json" \
  -d '{
    "objective": "控制 gamma 敞口",
    "risk_preference": "conservative",
    "time_horizon": "short_term"
  }'
```

AI 会根据当前状态生成交易建议。

### 5. 重算行为评分

```bash
curl -X POST http://localhost:8000/admin/behavior/rebuild \
  -H "Content-Type: application/json" \
  -d '{
    "window_days": 60
  }'
```

基于历史成交数据计算交易行为评分。

## 📊 使用 Swagger UI

访问 http://localhost:8000/docs 可以：
- 查看所有 API 接口
- 在线测试接口
- 查看请求/响应模型

## 🔧 常见问题

### Q1: 启动时报数据库错误

**A:** 确保在 backend 目录下运行，系统会自动创建 demo.db

### Q2: Tiger API 连接超时

**A:** 检查：
1. 私钥文件路径是否正确
2. tiger_id 是否正确
3. 网络连接是否正常
4. 是否需要配置代理

### Q3: 显示 "使用 Dummy 客户端"

**A:** 这是正常的！如果没有配置 Tiger API，系统会自动使用测试模式。

### Q4: Greeks 数据为 0

**A:** 可能原因：
- 使用 Dummy 客户端（测试模式）
- 账户中没有持仓
- API 权限不足

## 📚 下一步

1. **配置 Tiger API**
   - 参考 [TIGER_API_GUIDE.md](TIGER_API_GUIDE.md)
   - 获取真实持仓和 Greeks 数据

2. **配置 OpenAI**
   - 在 .env 中设置 OPENAI_API_KEY
   - 启用 AI 决策助手功能

3. **自定义风险参数**
   - 修改 `app/models/symbol_risk_profile.py`
   - 调整风险限额和评分规则

4. **集成到生产环境**
   - 使用 gunicorn 部署
   - 配置日志和监控
   - 设置数据库备份

## 💡 提示

- **安全第一**：始终先在 DRY_RUN 模式测试
- **风险管理**：设置合理的风险限额
- **监控告警**：定期检查系统状态和日志
- **备份数据**：定期备份数据库和配置文件

## 📞 获取帮助

- 查看 [README.md](README.md) 了解完整功能
- 阅读 [TIGER_API_GUIDE.md](TIGER_API_GUIDE.md) 解决 API 问题
- 查看 [TIGER_SDK_UPDATE.md](TIGER_SDK_UPDATE.md) 了解技术细节

---

**享受智能交易风控的便利！** 🎉
