import asyncio
import base64
import os
import random
import re
import time
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, At


VALID_MATCH_TYPES = ("contains", "exact", "regex")
VALID_REPLY_TYPES = ("text", "image", "mixed")
B64_PREFIX_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,")


@register(
    "astrbot_plugin_keyword_reply",
    "Zxin-Pro",
    "关键词自动回复",
    "群聊关键词自动回复插件，支持文本/图片/图文混合回复，模糊/精确/正则匹配，冷却、黑白名单等",
)
class KeywordReplyPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config or {}
        self._compiled_rules = []
        self._raw_rules_ref = None
        self._raw_rules_len = -1
        self._cooldown_map = {}
        self._self_id_cache = ""
        self._build_rules()

    async def initialize(self):
        logger.info(
            f"[keyword_reply] 已加载，规则数={len(self._compiled_rules)} "
            f"ignore_case={self.config.get('ignore_case', True)} "
            f"cooldown={self.config.get('cooldown_seconds', 0)}s"
        )

    async def terminate(self):
        self._compiled_rules = []
        self._cooldown_map.clear()

    # ---------- 配置解析 ----------

    def _build_rules(self):
        raw = self.config.get("rules") or []
        if not isinstance(raw, list):
            logger.warning("[keyword_reply] rules 配置不是列表，已忽略")
            raw = []
        self._raw_rules_ref = raw
        self._raw_rules_len = len(raw)

        compiled = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 格式错误（应为对象），已跳过")
                continue
            keyword = item.get("keyword")
            if not isinstance(keyword, str) or not keyword.strip():
                logger.warning(f"[keyword_reply] 规则#{idx + 1} keyword 为空，已跳过")
                continue
            keyword = keyword.strip()
            match_type = item.get("match_type") or "contains"
            if match_type not in VALID_MATCH_TYPES:
                logger.warning(
                    f"[keyword_reply] 规则#{idx + 1} match_type={match_type} 非法，回退为 contains"
                )
                match_type = "contains"

            regex_obj = None
            if match_type == "regex":
                flags = re.IGNORECASE if self.config.get("ignore_case", True) else 0
                try:
                    regex_obj = re.compile(keyword, flags)
                except re.error as e:
                    logger.warning(f"[keyword_reply] 规则#{idx + 1} 正则编译失败: {e}，已跳过")
                    continue

            replies = self._parse_replies(idx, item.get("replies"))
            if not replies:
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 无有效回复内容，已跳过")
                continue

            cooldown = item.get("cooldown")
            if not isinstance(cooldown, (int, float)) or cooldown < 0:
                cooldown = None  # 使用全局值
            reply_mode = item.get("reply_mode")
            if reply_mode not in ("sequential", "random"):
                reply_mode = None  # 使用全局值

            compiled.append(
                {
                    "keyword": keyword,
                    "match_type": match_type,
                    "regex": regex_obj,
                    "replies": replies,
                    "cooldown": cooldown,
                    "reply_mode": reply_mode,
                }
            )

        self._compiled_rules = compiled
        logger.info(f"[keyword_reply] 规则编译完成，有效规则数={len(compiled)}")

    def _parse_replies(self, idx, raw_replies):
        if not isinstance(raw_replies, list) or not raw_replies:
            return []
        replies = []
        for j, r in enumerate(raw_replies):
            if not isinstance(r, dict):
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 回复#{j + 1} 格式错误，已跳过")
                continue
            rtype = r.get("type")
            if rtype not in VALID_REPLY_TYPES:
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 回复#{j + 1} type={rtype} 非法，已跳过")
                continue
            content = r.get("content")
            if not isinstance(content, str) or not content.strip():
                logger.warning(f"[keyword_reply] 规则#{idx + 1} 回复#{j + 1} content 为空，已跳过")
                continue
            entry = {"type": rtype, "content": content.strip()}
            if rtype == "mixed":
                img = r.get("image")
                if isinstance(img, str) and img.strip():
                    entry["image"] = img.strip()
                elif not isinstance(img, str) or not img.strip():
                    logger.warning(
                        f"[keyword_reply] 规则#{idx + 1} 回复#{j + 1} mixed 缺少 image 字段，降级为纯文本"
                    )
                    entry["type"] = "text"
            replies.append(entry)
        return replies

    def _needs_rebuild(self) -> bool:
        raw = self.config.get("rules")
        if raw is not self._raw_rules_ref:
            return True
        if isinstance(raw, list) and len(raw) != self._raw_rules_len:
            return True
        return False

    # ---------- 匹配 ----------

    def _match(self, rule, text: str) -> bool:
        kw = rule["keyword"]
        ignore_case = self.config.get("ignore_case", True)
        if rule["match_type"] == "regex":
            try:
                return rule["regex"].search(text) is not None
            except Exception as e:
                logger.error(f"[keyword_reply] 正则匹配异常: {e}")
                return False
        if rule["match_type"] == "exact":
            a, b = (text, kw) if not ignore_case else (text.lower(), kw.lower())
            return a == b
        # contains
        a, b = (text, kw) if not ignore_case else (text.lower(), kw.lower())
        return b in a

    # ---------- 门控 ----------

    def _get_self_id(self, event: AstrMessageEvent) -> str:
        if self._self_id_cache:
            return self._self_id_cache
        try:
            self._self_id_cache = str(event.get_self_id() or "")
        except Exception:
            self._self_id_cache = ""
        return self._self_id_cache

    def _is_at_me(self, event: AstrMessageEvent) -> bool:
        self_id = self._get_self_id(event)
        if not self_id:
            return False
        try:
            comps = event.message_obj.message or []
        except Exception:
            return False
        for comp in comps:
            if isinstance(comp, At) and str(getattr(comp, "qq", "")) == self_id:
                return True
        return False

    def _pass_gates(self, event: AstrMessageEvent, group_id: str) -> bool:
        cfg = self.config
        if not group_id and cfg.get("group_only", True):
            return False
        sender_id = ""
        try:
            sender_id = str(event.get_sender_id() or "")
        except Exception:
            pass
        self_id = self._get_self_id(event)
        if self_id and sender_id == self_id:
            return False  # 机器人自身消息，防死循环
        if cfg.get("reply_on_at_only", False) and not self._is_at_me(event):
            return False
        if sender_id and sender_id in {str(x) for x in (cfg.get("blacklist_users") or [])}:
            return False
        try:
            if cfg.get("ignore_admin", False):
                admin = event.is_admin
                if callable(admin):
                    admin = admin()
                if admin:
                    return False
        except Exception:
            pass
        whitelist = {str(x) for x in (cfg.get("whitelist_groups") or [])}
        if whitelist and group_id not in whitelist:
            return False
        return True

    # ---------- 冷却 ----------

    def _cooldown_ok(self, group_id: str, rule) -> bool:
        global_cd = self.config.get("cooldown_seconds", 0)
        cd = rule.get("cooldown")
        cd = cd if cd is not None else global_cd
        try:
            cd = float(cd or 0)
        except (TypeError, ValueError):
            cd = 0
        if cd <= 0:
            return True
        key = (group_id, rule["keyword"])
        now = time.time()
        last = self._cooldown_map.get(key)
        if last is not None and now - last < cd:
            return False
        self._cooldown_map[key] = now
        if len(self._cooldown_map) > 512:
            for k in [k for k, v in self._cooldown_map.items() if now - v > cd * 2]:
                self._cooldown_map.pop(k, None)
        return True

    # ---------- 消息构造 ----------

    def _make_image(self, content: str) -> Optional[Image]:
        c = content.strip()
        if c.startswith(("http://", "https://")):
            return Image.fromURL(c)
        if os.path.isfile(c):
            return Image.fromFileSystem(c)
        b64 = B64_PREFIX_RE.sub("", c)
        compact = re.sub(r"\s+", "", b64)
        if len(compact) > 64 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
            try:
                base64.b64decode(compact, validate=True)
                return Image.fromBase64(compact)
            except Exception:
                pass
        logger.warning(f"[keyword_reply] 图片内容无法识别（非 URL/本地路径/Base64）: {c[:60]}")
        return None

    async def _send_replies(self, event: AstrMessageEvent, rule):
        mode = rule.get("reply_mode") or self.config.get("reply_mode", "sequential")
        replies = rule["replies"]
        if mode == "random":
            replies = [random.choice(replies)]
        for rep in replies:
            rtype = rep["type"]
            try:
                if rtype == "text":
                    yield event.plain_result(rep["content"])
                elif rtype == "image":
                    img = self._make_image(rep["content"])
                    if img is None:
                        yield event.plain_result("图片加载失败")
                    else:
                        yield event.image_result(img)
                elif rtype == "mixed":
                    chain = [Plain(rep["content"])]
                    img_url = rep.get("image")
                    img = self._make_image(img_url) if img_url else None
                    if img is not None:
                        chain.append(img)
                    yield event.chain_result(chain)
            except Exception as e:
                logger.error(f"[keyword_reply] 发送回复失败（{rtype}）: {e}")

    # ---------- 主监听 ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if self._needs_rebuild():
            self._build_rules()
        if not self._compiled_rules:
            return
        group_id = ""
        try:
            group_id = str(event.message_obj.group_id or "")
        except Exception:
            pass
        if not self._pass_gates(event, group_id):
            return
        text = (event.message_str or "").strip()
        if not text:
            return

        hit_any = False
        for rule in self._compiled_rules:
            if not self._match(rule, text):
                continue
            if not self._cooldown_ok(group_id, rule):
                logger.debug(f"[keyword_reply] 命中「{rule['keyword']}」但处于冷却，静默忽略")
                continue
            logger.info(
                f"[keyword_reply] 群 {group_id} 命中「{rule['keyword']}」"
                f"({rule['match_type']})，发送 {len(rule['replies'])} 条回复"
            )
            async for r in self._send_replies(event, rule):
                yield r
            hit_any = True
            if not self.config.get("match_all_rules", False):
                break
        # hit_any 仅供后续扩展；已发送过消息时 AstrBot 不会再触发 LLM 双响应
