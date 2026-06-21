# Furniture Choice C/S Demo

一个基于 FastAPI + LangChain/LangGraph checkpoint 的家具选择 C/S 网站骨架。

## 功能

- 用户注册并生成 `uid`
- 按 `uid` 保存偏好与历史总结记录
- 支持文字需求、预算、图片上传
- 通过 web search 搜索宜家家具候选并组合推荐
- 输出购买建议、商品图片、总金额
- 使用 LangGraph checkpointer 按 `uid` 记住对话状态

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000

## 环境变量

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"
export OPENAI_IMAGE_MODEL="gpt-image-1"  # 可选，用于生成家具效果图
export TAVILY_API_KEY="..."  # 可选；没有时使用内置演示商品
```

`TAVILY_API_KEY` 用于 web search 宜家商品。没有配置时，接口仍可跑通，但会返回模拟的 IKEA 候选商品。

图片展示不会使用宜家商品图：如果配置了 `OPENAI_API_KEY`，会调用图片生成模型生成一张整体房间效果图；如果未配置，则只展示家具摆放方案，不再用 SVG 示意图冒充真实效果图。设置 `DISABLE_AI_IMAGES=true` 可以关闭图片模型调用。
