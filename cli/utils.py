import questionary
from datetime import datetime
from rich.console import Console
import os

console = Console()

def get_trigger_time() -> str:
    """提示用户输入触发时间"""
    now = datetime.now()
    time_options = [
        f"A股当前时间 ({now.strftime('%Y-%m-%d %H:%M:%S')})",
    ]
    
    time_choice = questionary.select(
        "选择触发时间:（其他时间请期待后续版本）",
        choices=time_options,
        style=questionary.Style([
            ("text", "fg:white"),
            ("highlighted", "fg:green bold"),
            ("pointer", "fg:green"),
        ])
    ).ask()
    
    if time_choice == time_options[0]:
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    else:
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')}"

def validate_llm_connection():
    """验证LLM连接"""
    try:
        # Import LLM model when needed
        from contest_trade.models.llm_model import GLOBAL_LLM
        
        console.print("🔍 [cyan]正在验证LLM配置...[/cyan]")
        test_messages = [
            {"role": "user", "content": "请回复'连接测试成功'，不要添加任何其他内容。"}
        ]
        result = GLOBAL_LLM.run(test_messages, max_tokens=1, temperature=0.1, max_retries=0)
        if result and hasattr(result, 'content') and result.content:
            console.print(f"✅ [green]LLM连接成功[/green] - 模型: {GLOBAL_LLM.model_name}")
            return True
        else:
            console.print("❌ [red]LLM连接失败 - 无响应内容[/red]")
            return False
    except Exception as e:
        console.print(f"❌ [red]LLM连接失败: {str(e)}[/red]")
        return False

def validate_required_services():
    """验证 AKShare 和主 LLM 是否可用。"""
    console.print("\n" + "="*50)
    console.print("🔧 [bold blue]正在验证必要系统配置...[/bold blue]")
    console.print("="*50)
    all_valid = True
    
    try:
        import akshare  # noqa: F401
        console.print("✅ [green]AKShare已安装[/green]")
    except ImportError:
        console.print("❌ [red]AKShare未安装，请重新安装项目依赖[/red]")
        all_valid = False
    
    # 始终验证LLM
    if not validate_llm_connection():
        all_valid = False
    
    console.print("="*50)
    
    if all_valid:
        console.print("🎉 [bold green]所有必要系统配置验证通过，系统准备就绪！[/bold green]")
        console.print("="*50 + "\n")
        return True
    else:
        console.print("⚠️  [bold red]必要系统配置验证失败，请检查配置文件[/bold red]")
        console.print("="*50 + "\n")
        return False

def get_market_selection() -> str:
    """项目仅支持 A 股市场。"""
    return "CN-Stock"

def get_trigger_time_for_market(market: str, silent: bool = False) -> str:
    """根据市场获取对应的触发时间，并设置环境变量"""
    # 设置环境变量
    os.environ['CONTEST_TRADE_MARKET'] = market

    # 根据市场获取触发时间
    if market != "CN-Stock":
        return None
    if silent:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return get_trigger_time()
