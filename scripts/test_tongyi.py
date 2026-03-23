"""测试 ChatTongyi 调用 qwen3.5-plus 模型"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_community.chat_models import ChatTongyi
from config.settings import get_settings


def test_with_openai_compatible():
    """使用 OpenAI 兼容接口测试 (DashScope 新版 API)"""
    settings = get_settings()

    if not settings.dashscope_api_key:
        print("错误: 未设置 dashscope_api_key")
        return

    from openai import OpenAI

    # DashScope OpenAI 兼容 endpoint
    client = OpenAI(
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    models = ["qwen3-max", "qwen3.5-plus", "qwen-plus", "qwen-turbo"]

    for model_name in models:
        print(f"\n{'='*50}")
        print(f"[OpenAI 兼容接口] 测试模型: {model_name}")
        print('='*50)

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
                temperature=0.3
            )

            print(f"✅ {model_name} 调用成功!")
            content = response.choices[0].message.content
            print(f"响应: {content[:150]}...")

        except Exception as e:
            print(f"❌ {model_name} 调用失败!")
            print(f"错误: {type(e).__name__}: {str(e)[:300]}")


def test_with_dashscope_sdk():
    """使用 DashScope 原生 SDK 测试"""
    settings = get_settings()

    if not settings.dashscope_api_key:
        print("错误: 未设置 dashscope_api_key")
        return

    try:
        import dashscope
        from dashscope import Generation

        dashscope.api_key = settings.dashscope_api_key

        models = ["qwen3-max", "qwen3.5-plus", "qwen-plus"]

        for model_name in models:
            print(f"\n{'='*50}")
            print(f"[DashScope SDK] 测试模型: {model_name}")
            print('='*50)

            try:
                response = Generation.call(
                    model=model_name,
                    messages=[{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
                    result_format='message'
                )

                if response.status_code == 200:
                    print(f"✅ {model_name} 调用成功!")
                    content = response.output.choices[0].message.content
                    print(f"响应: {content[:150]}...")
                else:
                    print(f"❌ {model_name} 调用失败!")
                    print(f"状态码: {response.status_code}")
                    print(f"错误: {response.code} - {response.message}")

            except Exception as e:
                print(f"❌ {model_name} 异常: {type(e).__name__}: {str(e)[:200]}")

    except ImportError:
        print("DashScope SDK 未安装，跳过原生 SDK 测试")
        print("安装命令: pip install dashscope")


def test_qwen_models():
    """测试 qwen3-max 和 qwen3.5-plus 两个模型"""
    settings = get_settings()

    if not settings.dashscope_api_key:
        print("错误: 未设置 dashscope_api_key，请检查 .env 文件")
        return

    # 要测试的模型列表 - 尝试可能的 qwen3.5 模型名称
    models = [
        "qwen3-max",
        "qwen3.5-plus",
        "qwen3.5-turbo",
        "qwen-plus",
        "qwen-turbo",
        "qwen2.5-plus",
        "qwen2.5-turbo",
    ]

    for model_name in models:
        print(f"\n{'='*50}")
        print(f"测试模型: {model_name}")
        print('='*50)

        try:
            llm = ChatTongyi(
                model=model_name,
                dashscope_api_key=settings.dashscope_api_key,
                temperature=0.3
            )

            # 简单测试调用
            response = llm.invoke("你好，请用一句话介绍你自己。")

            print(f"✅ {model_name} 调用成功!")
            print(f"响应: {response.content[:200]}...")

        except Exception as e:
            print(f"❌ {model_name} 调用失败!")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")

    print(f"\n{'='*50}")
    print("测试完成")
    print('='*50)


if __name__ == "__main__":
    print("=" * 60)
    print("测试 1: OpenAI 兼容接口 (DashScope 新版)")
    print("=" * 60)
    test_with_openai_compatible()

    print("\n" + "=" * 60)
    print("测试 2: DashScope 原生 SDK")
    print("=" * 60)
    test_with_dashscope_sdk()

    print("\n" + "=" * 60)
    print("测试 3: LangChain ChatTongyi")
    print("=" * 60)
    test_qwen_models()