# astrbot_plugin_keyword_reply（群聊关键词监控）

AstrBot 群聊关键词监控插件：检测群聊消息中的关键词，命中后发送自定义文本 / 图片 / 图文混合。独立运行，不干扰正常 LLM 对话。

## 功能

- 仅监听群聊消息（GROUP_MESSAGE），私聊不处理
- 三种回复类型：`text` 纯文本 / `image` 纯图片 / `text_image` 文本+图片（合并为一条消息）
- 两种匹配模式：`contains` 包含匹配（默认）/ `regex` 正则匹配（启动时预编译，非法正则自动跳过）
- 规则级 `groups` 生效群过滤（留空=全部群）、`enabled` 启用/禁用、`exclude_words` 排除词（可选）
- 群聊黑名单 / 用户白名单（白名单留空=所有用户可触发）
- 一条消息命中多条规则：默认只触发第一条，可配置全部触发（规则间加延迟防风控）
- 防死循环：机器人自身消息不处理
- rules 为空或插件禁用时静默返回，不报错
- 配置热更新：面板改规则后无需重启，下条消息自动生效

## 配置项（_conf_schema.json）

| 配置项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| enable | bool | true | 总开关 |
| group_blacklist | list | [] | 群聊黑名单，名单中的群不触发 |
| user_whitelist | list | [] | 用户白名单，留空=所有人；非空=仅名单内用户触发 |
| match_all_rules | bool | false | 命中多条规则时是否全部触发 |
| delay_seconds | float | 0.3 | 多条回复之间的间隔秒数（防风控） |
| ignore_case | bool | true | 忽略大小写 |
| rules | template_list | [] | 规则卡片列表（面板可视化添加，无需写 JSON） |

## rules 规则字段（面板卡片式配置）

在插件配置页点「关键词规则」模板按钮即可添加一条规则，每条规则一张卡片：

| 字段 | 说明 |
|---|---|
| 触发关键词 | 必填；regex 模式时填正则表达式 |
| 匹配方式 | contains=包含即触发（默认）/ regex=正则匹配（下拉选择） |
| 回复类型 | text=纯文本 / image=纯图片 / text_image=文本+图片合并一条（下拉选择） |
| 回复文本 | text / text_image 时使用 |
| 回复图片 | image / text_image 时使用，图片 URL 或本地绝对路径 |
| 生效群号 | 留空=所有群生效 |
| 排除词 | 可选，消息包含任一排除词则不触发 |
| 启用该规则 | 默认开启，可单独停用某条规则 |

> 仓库与配置中均不预置任何示例规则，全部由用户在 AstrBot 管理面板自行添加。

## 安装

1. 方式一：把本目录放进 AstrBot `data/plugins/`，在管理面板「插件管理」中启用
2. 方式二：管理面板插件页 → 从 GitHub 仓库导入 `Zxin-Pro/astrbot_plugin_keyword_reply`

## 使用

1. 面板打开插件配置
2. 在 `rules` 中添加规则（keyword 必填，其余按需）
3. 保存即可生效（若未生效请在插件管理中重载插件）

## 版本兼容说明

- 按 AstrBot v4.x 编写：`filter.EventMessageType.GROUP_MESSAGE`、`event.get_group_id()`、`event.get_sender_id()`
- 若旧版 `get_group_id()` 不存在，代码已自动回退到 `event.message_obj.group_id`
