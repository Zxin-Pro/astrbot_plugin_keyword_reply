# -*- coding: utf-8 -*-
"""
群聊关键词监控 (keyword_reply)
检测群聊关键词，命中后发送自定义文本或图片。
仅监听群聊消息，不干扰正常 LLM 对话。

注意：不同 AstrBot 版本 API 可能存在差异，本插件按较新版（v4.x）编写：
- @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE) 监听群聊
- event.get_group_id() / event.get_sender_id() / event.get_self_id()
- 若旧版没有 get_group_id()，可改用 event.message_obj.group_id
"""

import asyncio
import os
import re

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain

# ---- 插件元数据（部分版本的面板会读取模块级元数据） ----
__plugin_name__ = "群聊关键词监控"
__plugin_version__ = "v2.2.0"
__plugin_author__ = "Zxin-Pro"
__plugin_description__ = "检测群聊关键词，命中后发送自定义文本或图片（支持文本/图片/图文，正则匹配，排除词，群黑名单，用户白名单）"

# 合法取值
_VALID_MATCH_TYPES = ("contains", "regex")
_VALID_REPLY_TYPES = ("text", "image", "text_image")


@register(
    "astrbot_plugin_keyword_reply",
    "Zxin-Pro",
    "群聊关键词监控",
    __plugin_description__,
)
class KeywordReplyPlugin(Star):
    """群聊关键词监控插件主类"""

    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config or {}
        self._rules = []          # 编译后的规则（内存缓存，避免每条消息重复解析/编译正则）
        self._raw_rules_ref = None
        self._raw_rules_len = -1
        self._self_id_cache = ""
        self._build_rules()

    # ================= 生命周期 =================

    async def initialize(self):
        logger.info(
            f"[keyword_reply] 群聊关键词监控已加载："
            f"enable={self.config.get('enable', True)}，"
            f"有效规则数={len(self._rules)}"
        )

    async def terminate(self):
        self._rules = []
        logger.info("[keyword_reply] 插件已卸载")

    # ================= 配置解析 =================

    def _resolve_uploaded_file(self, rel_path: str):
        """把配置页上传的文件相对路径解析为插件目录下的绝对路径（含安全校验）。"""
        rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
        if not rel.startswith("files/") or ".." in rel.split("/"):
            logger.warning(f"[keyword_reply] 非法上传文件路径: {rel_path}")
            return None
        base = os.path.dirname(os.path.abspath(__file__))
        abs_path = os.path.normpath(os.path.join(base, rel))
        if not abs_path.startswith(os.path.normpath(base)):
            logger.warning(f"[keyword_reply] 上传文件路径越界: {rel_path}")
            return None
        if not os.path.isfile(abs_path):
            return None
        return abs_path

    def _build_rules(self):
        """启动/配置变更时把 rules 解析到内存：校验字段、预编译正则。"""
        raw = self.config.get("rules") or []
        if not isinstance(raw, list):
            logger.warning("[keyword_reply] rules 配置不是列表，已忽略")
            raw = []
        self._raw_rules_ref = raw
        self._raw_rules_len = len(raw)

        ignore_case = self.config.get("ignore_case", True)
        regex_flags = re.IGNORECASE if ignore_case else 0

        compiled = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 不是对象，已跳过")
                continue

            # keyword：必填
            keyword = item.get("keyword")
            if not isinstance(keyword, str) or not keyword.strip():
                logger.warning(f"[keyword_reply] 规则#{idx + 1} keyword 为空，已跳过")
                continue
            keyword = keyword.strip()

            # enabled：默认 True
            enabled = item.get("enabled", True)
            if enabled is not True and str(enabled).lower() not in ("true", "1", "yes"):
                enabled = False
            else:
                enabled = True

            # match_type：默认 contains
            match_type = item.get("match_type") or "contains"
            if match_type not in _VALID_MATCH_TYPES:
                logger.warning(
                    f"[keyword_reply] 规则#{idx + 1} match_type={match_type} 非法，回退为 contains"
                )
                match_type = "contains"

            # 正则预编译，非法正则跳过该规则
            regex_obj = None
            if match_type == "regex":
                try:
                    regex_obj = re.compile(keyword, regex_flags)
                except re.error as e:
                    logger.warning(f"[keyword_reply] 规则#{idx + 1} 正则编译失败: {e}，已跳过")
                    continue

            # reply_type 与回复内容
            reply_type = item.get("reply_type") or "text"
            if reply_type not in _VALID_REPLY_TYPES:
                logger.warning(
                    f"[keyword_reply] 规则#{idx + 1} reply_type={reply_type} 非法，回退为 text"
                )
                reply_type = "text"
            reply_text = item.get("reply_text") or ""
            reply_image = str(item.get("reply_image") or "").strip()
            if reply_type in ("text", "text_image") and not reply_text.strip():
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 需要 reply_text 但为空，已跳过")
                continue
            if reply_type in ("image", "text_image") and not reply_image:
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 需要 reply_image 但为空，已跳过")
                continue

            # 配置页上传的图片（file 类型，值为相对插件目录的路径列表），优先于 reply_image
            upload_files = [
                str(p).strip()
                for p in (item.get("reply_image_file") or [])
                if isinstance(p, str) and str(p).strip()
            ]
            if reply_type in ("image", "text_image") and upload_files:
                resolved = self._resolve_uploaded_file(upload_files[0])
                if resolved:
                    reply_image = resolved
                else:
                    logger.warning(
                        f"[keyword_reply] 规则#{idx + 1} 上传图片不存在: {upload_files[0]}，"
                        f"回退使用 reply_image"
                    )

            # 生效群号：留空=全部群
            groups = {str(g) for g in (item.get("groups") or []) if str(g).strip()}

            # 排除词（可选）：消息包含任一排除词则不触发
            exclude_words = [
                str(w).strip()
                for w in (item.get("exclude_words") or [])
                if isinstance(w, str) and w.strip()
            ]

            compiled.append(
                {
                    "keyword": keyword,
                    "match_type": match_type,
                    "regex": regex_obj,
                    "reply_type": reply_type,
                    "reply_text": reply_text,
                    "reply_image": reply_image,
                    "groups": groups,
                    "exclude_words": exclude_words,
                    "enabled": enabled,
                }
            )

        self._rules = compiled
        logger.info(f"[keyword_reply] 规则加载完成，有效规则数={len(compiled)}")

    def _needs_rebuild(self) -> bool:
        """检测配置里 rules 是否被替换（面板改配置后无需重启即可生效）。"""
        raw = self.config.get("rules")
        if raw is not self._raw_rules_ref:
            return True
        if isinstance(raw, list) and len(raw) != self._raw_rules_len:
            return True
        return False

    # ================= 匹配与过滤 =================

    def _match(self, rule, text: str) -> bool:
        """单条规则匹配：contains 包含 / regex 正则。"""
        if rule["match_type"] == "regex":
            try:
                return rule["regex"].search(text) is not None
            except Exception as e:  # 防御性兜底
                logger.error(f"[keyword_reply] 正则匹配异常: {e}")
                return False
        # contains：忽略大小写可配置
        if self.config.get("ignore_case", True):
            return rule["keyword"].lower() in text.lower()
        return rule["keyword"] in text

    def _get_self_id(self, event: AstrMessageEvent) -> str:
        if not self._self_id_cache:
            try:
                self._self_id_cache = str(event.get_self_id() or "")
            except Exception:
                self._self_id_cache = ""
        return self._self_id_cache

    def _pass_gates(self, event: AstrMessageEvent, group_id: str, sender_id: str) -> bool:
        """全局门控：群黑名单、用户白名单、机器人自身消息。"""
        cfg = self.config
        # 机器人自身消息不处理（防止回复内容再次命中关键词导致死循环）
        self_id = self._get_self_id(event)
        if self_id and sender_id == self_id:
            return False
        # 群聊黑名单
        blacklist = {str(g) for g in (cfg.get("group_blacklist") or [])}
        if group_id in blacklist:
            return False
        # 用户白名单：留空=所有用户；非空=仅名单内用户触发
        whitelist = {str(u) for u in (cfg.get("user_whitelist") or [])}
        if whitelist and sender_id not in whitelist:
            return False
        return True

    # ================= 发送 =================

    def _make_image(self, content: str):
        """根据内容构造 Image 组件（支持 http(s) URL 或本地绝对路径）。"""
        c = (content or "").strip()
        if c.startswith(("http://", "https://")):
            return Image.fromURL(c)
        if os.path.isfile(c):
            return Image.fromFileSystem(c)
        logger.warning(f"[keyword_reply] 图片地址无法识别（非 URL/本地路径）: {c[:60]}")
        return None

    async def _send_rule(self, event: AstrMessageEvent, rule):
        """按 reply_type 发送对应内容。"""
        rt = rule["reply_type"]
        try:
            if rt == "text":
                yield event.plain_result(rule["reply_text"])
            elif rt == "image":
                if rule["reply_image"].startswith(("http://", "https://")):
                    yield event.image_result(rule["reply_image"])
                else:
                    img = self._make_image(rule["reply_image"])
                    if img is not None:
                        # 本地路径用 MessageChain 构造，兼容性更好
                        yield event.chain_result([img])
            elif rt == "text_image":
                # 合并为一条消息：文本 + 图片
                chain = []
                if rule["reply_text"].strip():
                    chain.append(Plain(rule["reply_text"]))
                img = self._make_image(rule["reply_image"])
                if img is not None:
                    chain.append(img)
                if chain:
                    yield event.chain_result(chain)
        except Exception as e:
            logger.error(f"[keyword_reply] 发送回复失败（{rt}）: {e}")

    # ================= 主监听 =================

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """群聊消息监听：命中关键词即回复。未启用/无规则时静默返回。"""
        try:
            # 全局开关
            if not self.config.get("enable", True):
                return
            # 配置热更新检测
            if self._needs_rebuild():
                self._build_rules()
            # 无规则：静默返回，不做任何处理
            if not self._rules:
                return

            # 群号（旧版本若没有 get_group_id，可改用 event.message_obj.group_id）
            try:
                group_id = str(event.get_group_id() or "")
            except Exception:
                group_id = str(getattr(getattr(event, "message_obj", None), "group_id", "") or "")
            if not group_id:
                return
            try:
                sender_id = str(event.get_sender_id() or "")
            except Exception:
                sender_id = ""
            if not self._pass_gates(event, group_id, sender_id):
                return

            text = (event.message_str or "").strip()
            if not text:
                return

            # 收集命中的规则（保持配置顺序）
            matched = []
            for rule in self._rules:
                if not rule["enabled"]:
                    continue
                # 规则级生效群过滤：留空=全部群
                if rule["groups"] and group_id not in rule["groups"]:
                    continue
                # 排除词：包含任一排除词则不触发
                if any(w in text for w in rule["exclude_words"]):
                    continue
                if not self._match(rule, text):
                    continue
                matched.append(rule)
                # 只触发第一条（可配置）
                if not self.config.get("match_all_rules", False):
                    break

            if not matched:
                return

            logger.info(
                f"[keyword_reply] 群 {group_id} 用户 {sender_id} 命中规则: "
                f"{[r['keyword'] for r in matched]}"
            )

            # 依次发送，多条之间加延迟防风控
            delay = self.config.get("delay_seconds", 0.3)
            try:
                delay = max(0.0, float(delay))
            except (TypeError, ValueError):
                delay = 0.3
            for i, rule in enumerate(matched):
                if i > 0 and delay > 0:
                    await asyncio.sleep(delay)
                async for r in self._send_rule(event, rule):
                    yield r
        except Exception as e:
            # 任何异常都不能让插件崩溃或影响其他消息处理
            logger.error(f"[keyword_reply] 处理消息时出现未预期异常: {e}")
