# astrbot_plugin_keyword_reply

AstrBot 群聊关键词自动回复插件。消息命中关键词即自动回复对应内容，支持文本 / 图片 / 图文混合。

## 功能

- 关键词监听：监听群聊全部消息，命中即回复
- 三种匹配模式（每条规则可单独设置）：
  - `contains` 模糊匹配（默认）：消息包含关键词即触发
  - `exact` 精确匹配：消息文本完全等于关键词才触发
  - `regex` 正则匹配：关键词作为正则表达式使用（启动时预编译）
- 三种回复类型：`text` 纯文本 / `image` 纯图片 / `mixed` 图文混合
- 图片 content 支持：http(s) URL、本地绝对路径、Base64（含 `data:image/...;base64,` 前缀）
- 一个关键词可配置多条回复：依次全部发送或随机发送一条（全局或规则级配置）
- 冷却控制：同一关键词在同一群 N 秒内只触发一次（全局或规则级）
- 群白名单 / 用户黑名单 / 仅@触发 / 跳过管理员 / 仅群聊生效，均可配置
- 防死循环：自动忽略机器人自身消息
- 命中多个关键词：可配置只触发第一个或全部依次触发
- 规则较多时正则启动时预编译，不重复编译

## 配置示例（rules）

```json
[
  {
    "keyword": "你好",
    "match_type": "contains",
    "replies": [
      { "type": "text", "content": "你好呀~" },
      { "type": "image", "content": "https://example.com/hello.jpg" }
    ]
  },
  {
    "keyword": "^签到$",
    "match_type": "regex",
    "cooldown": 60,
    "replies": [
      { "type": "mixed", "content": "签到成功！", "image": "/data/img/checkin.png" }
    ]
  }
]
```

规则内可选字段：

| 字段 | 说明 |
|---|---|
| `cooldown` | 该规则独立冷却秒数，覆盖全局 `cooldown_seconds` |
| `reply_mode` | `sequential`（依次发）或 `random`（随机一条），覆盖全局 |

## 安装

将本目录放入 AstrBot `data/plugins/` 后在管理面板启用，或在面板插件市场页从 GitHub 导入。

## 备注

- 私聊默认不触发（`group_only` 可关）
- 图片内容无法识别（非 URL / 本地路径 / Base64）时回复"图片加载失败"，mixed 只发文本部分
- 修改配置后需在面板重载插件生效
