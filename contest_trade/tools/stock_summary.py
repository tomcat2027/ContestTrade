import hashlib
import asyncio
from pathlib import Path
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# --- Imports from project ---
from utils.tushare_utils import pro_cached
from models.llm_model import GLOBAL_VISION_LLM
from tools.search_web import search_web
from utils.stock_data_provider import get_all_stock_data
from tools.tool_utils import smart_tool

# --- Tool Setup ---
TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "stock_basic_info_cache"

# --- Pydantic Models ---
class StockSummaryInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The A-share symbol, such as '600519.SH'.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")

# --- Helper Functions ---
def get_stock_name_by_code(symbol, market):
    """Gets the stock name from its symbol and market."""
    if market == "CN-Stock":
        df = pro_cached.run("stock_basic", func_kwargs={'ts_code': symbol, 'fields': 'ts_code,name'}, verbose=False)
        return df.iloc[0]['name'] if df is not None and not df.empty else symbol
    return symbol

async def call_llm_for_comprehensive_analysis(prompt, intraday_chart_base64=None, kline_chart_base64=None):
    """Calls the LLM for a comprehensive analysis with text and images."""
    
    content = [{"type": "text", "text": prompt}]
    if intraday_chart_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{intraday_chart_base64}"}})
    if kline_chart_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{kline_chart_base64}"}})
    
    messages = [{"role": "user", "content": content}]
    response = await GLOBAL_VISION_LLM.a_run(messages, temperature=0.3, max_tokens=4000, verbose=False, thinking=False)
    return response.content

# --- Main Analysis Function (Refactored) ---
async def analyze_stock_basic_info(market, symbol, stock_name, trigger_time):
    """Main analysis function, simplified to use the new data provider."""
    
    # 1. Get all data in one call
    print("📊  Fetching all stock data...")
    all_data = get_all_stock_data(market, symbol, stock_name, trigger_time)
    print("✅  Data fetching complete.")

    # 2. Get news data
    try:
        news_result = await search_web.ainvoke({"query": f"{stock_name}", "topk": 10, "trigger_time": trigger_time})
        news_analysis = '\n'.join(map(str, news_result)) if isinstance(news_result, list) else str(news_result)
        print("✅  News fetching complete.")
    except Exception as e:
        news_analysis = f"相关新闻获取失败: {e}"
        print(f"❌  News fetching failed: {e}")

    # 3. Build the comprehensive prompt
    prompt_template = f"""请为{stock_name}({symbol})生成一份专业的股票基本信息分析报告。
分析时间: {trigger_time}

我将为您提供当日分时走势图、90日K线图表以及以下多维度数据，请结合图表进行精准分析。

=== 数据输入 ===

【分时走势数据】
{all_data['intraday_description']}

【K线技术数据】
{all_data['kline_description']}

【财务基本面数据】
{all_data['financial_summary']}

【板块资金流向数据】
{all_data['sector_analysis']}

【个股资金流向数据（近三日）】
{all_data['stock_moneyflow_analysis']}

【技术面因子数据】
{all_data['technical_analysis']}

【新闻事件数据】
{news_analysis}

=== 分析要求 ===

请严格按照以下结构输出分析报告：

## 一、技术面分析
1. **分时走势特征**：基于分时图和数据，分析当日价格波动特点、成交量分布、关键时点
2. **K线技术形态**：基于90日K线图走势以及近7日K线数据，识别技术形态、趋势方向、关键支撑阻力位
3. **技术指标信号**：解读RSI、MACD、KDJ、布林带等指标，判断短期动能

## 二、基本面分析
1. **盈利能力**：分析毛利率、净利率、ROE等核心指标
2. **成长性**：评估营收增长、净利润增长的可持续性
3. **财务健康度**：分析资产负债率、现金流、偿债能力

## 三、市场环境分析
1. **板块表现**：分析所在行业的资金流向和市场地位
2. **资金动向**：解读个股资金流向，判断机构和散户行为

## 四、消息面分析
筛选并分析对股价有实质影响的新闻事件，排除无关信息

## 五、综合评估
1. **核心结论**：技术面、基本面、市场面的综合判断
2. **关键风险点**：识别主要风险因素
3. **数据局限性**：说明分析中的数据缺失或不确定性

=== 输出要求 ===
- 语言：专业、客观、精准
- 长度：控制在1500-2000字
- 结构：严格按照上述五个部分组织
- 图表：充分结合分时图和K线图进行分析
- 避免：投资建议、主观判断、冗余信息
"""
    # 4. Call LLM for analysis
    print("🤖  Starting LLM comprehensive analysis...")
    try:
        analysis_result = await call_llm_for_comprehensive_analysis(
            prompt_template, 
            all_data['intraday_chart_base64'], 
            all_data['kline_chart_base64']
        )
        return analysis_result
    except Exception as e:
        print(f"❌  LLM analysis failed: {e}")
        return f'LLM分析失败: {e}'

# --- Tool Definition ---
@smart_tool(
    description="A股基本信息综合分析工具。输入股票代码和触发时间，返回技术面、基本面、资金面和新闻事件总结。",
    args_schema=StockSummaryInput,
    max_output_len=4000,
    timeout_seconds=120.0
)
async def stock_summary(market: str, symbol: str, trigger_time: str) -> str:
    """New version of the stock summary tool with refactored logic."""
    if market != "CN-Stock":
        return f"错误：不支持的市场类型 '{market}'。"

    if not TOOL_CACHE.exists():
        TOOL_CACHE.mkdir(parents=True, exist_ok=True)
    
    cache_key = f"{market}_{symbol}_{trigger_time.split(' ')[0]}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"

    if cache_file.exists():
        return cache_file.read_text()
    else:
        stock_name = get_stock_name_by_code(symbol, market)
        result = await analyze_stock_basic_info(market, symbol, stock_name, trigger_time)
        cache_file.write_text(result)
        return result


if __name__ == "__main__":
    pass
