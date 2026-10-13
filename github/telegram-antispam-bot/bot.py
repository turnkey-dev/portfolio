"""Telegram anti-spam bot. Python 3.10+, standard library only."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from spam_filter import classify

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("antispam")


def acquire_instance_lock():
    """Keep the returned handle alive until process exit; Windows releases on crash."""
    import msvcrt
    directory = ROOT / "data"
    directory.mkdir(exist_ok=True)
    handle = (directory / "bot.lock").open("a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise ValueError("Другой экземпляр бота уже работает. Сначала остановите его в другом окне.") from None
    return handle


def load_env(path):
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, sep, value = line.partition("=")
                if not sep:
                    raise ValueError("В .env найдена строка без знака =")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def ids(value):
    return {int(x.strip()) for x in value.split(",") if x.strip()}


class APIError(Exception):
    def __init__(self, code, description, retry_after=0):
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


class Telegram:
    def __init__(self, token):
        self.token = token

    def call(self, method, **data):
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/{method}",
            data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read())
            except (ValueError, OSError):
                raise APIError(exc.code, f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            # Never log urllib errors: their URL can contain the bot token.
            raise APIError(503, "Нет соединения с Telegram") from None
        if not result.get("ok"):
            description = str(result.get("description", "Ошибка API")).replace(self.token, "[TOKEN]")
            raise APIError(result.get("error_code", 500), description,
                           result.get("parameters", {}).get("retry_after", 0))
        return result["result"]


class Moderator:
    def __init__(self, api, me, *, dry_run=False, threshold=7, chats=None, whitelist=None):
        self.api, self.me = api, me
        self.dry_run, self.threshold = dry_run, threshold
        self.chats, self.whitelist = chats or set(), whitelist or set()

    def handle(self, update):
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat = message["chat"]
        chat_id = chat["id"]
        text = message.get("text") or message.get("caption") or ""
        sender = message.get("from", {})
        command = text.split(maxsplit=1)[0].lower() if text else ""
        name, _, target = command.partition("@")
        addressed = not target or target == self.me.get("username", "").lower()
        if name == "/chatid" and addressed:
            self.api.call("sendMessage", chat_id=chat_id, text=f"ID этого чата: {chat_id}")
            return
        if chat["type"] not in {"group", "supergroup"}:
            if name == "/start" and addressed:
                self.api.call("sendMessage", chat_id=chat_id,
                              text="Добавьте меня в группу администратором с правами удаления сообщений и блокировки участников. /chatid — ID чата.")
            return
        if self.chats and chat_id not in self.chats:
            return
        # sender_chat is an anonymous admin or channel, not the synthetic 'from' user.
        if message.get("sender_chat") or not sender or sender["id"] == self.me["id"]:
            return
        if sender["id"] in self.whitelist:
            return
        verdict = classify(text, self.threshold)
        if not verdict.spam:
            return
        # Fresh lookup before destructive actions; failures propagate, never assume non-admin.
        member = self.api.call("getChatMember", chat_id=chat_id, user_id=sender["id"])
        if member["status"] in {"creator", "administrator"}:
            return
        context = f"chat={chat_id} message={message['message_id']} user={sender['id']} score={verdict.score} reasons={','.join(verdict.reasons)}"
        if self.dry_run:
            LOG.info("TEST %s", context)
            return
        # Both operations are attempted even if one gets a permanent API rejection.
        transient = None
        for method, parameters in [
            ("deleteMessage", {"message_id": message["message_id"]}),
            ("banChatMember", {"user_id": sender["id"], "revoke_messages": True}),
        ]:
            try:
                self.api.call(method, chat_id=chat_id, **parameters)
                LOG.info("OK %s %s", method, context)
            except APIError as exc:
                LOG.error("FAIL %s %s: %s", method, context, exc)
                if exc.code == 429 or exc.code >= 500:
                    transient = exc
        if transient:
            raise transient


def main():
    load_env(ROOT / ".env")
    token = os.getenv("BOT_TOKEN", "")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("Укажите BOT_TOKEN от @BotFather в файле .env")
    threshold = int(os.getenv("SPAM_THRESHOLD", "7"))
    if threshold < 1:
        raise ValueError("SPAM_THRESHOLD должен быть положительным")
    dry_value = os.getenv("DRY_RUN", "false").lower()
    if dry_value not in {"true", "false"}:
        raise ValueError("DRY_RUN должен быть true или false")
    chats = ids(os.getenv("ALLOWED_CHAT_IDS", ""))
    whitelist = ids(os.getenv("WHITELIST_USER_IDS", ""))
    state_dir = ROOT / "data"
    state_dir.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), RotatingFileHandler(
                            state_dir / "moderation.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")])
    api = Telegram(token)
    me = api.call("getMe")
    webhook = api.call("getWebhookInfo")
    if webhook.get("url"):
        raise ValueError("У бота настроен webhook. Используйте отдельного бота без webhook для этого проекта.")
    # Validate configured groups before consuming updates.
    for chat_id in chats:
        member = api.call("getChatMember", chat_id=chat_id, user_id=me["id"])
        if member["status"] != "administrator" or not all(
                member.get(right) for right in ("can_delete_messages", "can_restrict_members")):
            raise ValueError(f"В чате {chat_id} нужны права администратора: удаление и блокировка")
    moderator = Moderator(api, me, dry_run=dry_value == "true", threshold=threshold,
                          chats=chats, whitelist=whitelist)
    # State is scoped to bot identity; changing tokens cannot inherit another bot's offset.
    offset_file = state_dir / f"offset-{me['id']}.json"
    offset = json.loads(offset_file.read_text()) if offset_file.exists() else 0
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("Некорректный файл offset в data")
    LOG.info("Бот @%s запущен. Режим: %s", me.get("username"), "ТЕСТ" if moderator.dry_run else "УДАЛЕНИЕ + БАН")
    while True:
        try:
            updates = api.call("getUpdates", offset=offset, timeout=30,
                               allowed_updates=["message", "edited_message"])
            for update in updates:
                try:
                    moderator.handle(update)
                except APIError as exc:
                    if exc.code in {401, 409, 429} or exc.code >= 500:
                        raise
                    LOG.error("Update %s пропущен: %s", update["update_id"], exc)
                # Advance only after handling. Repeated moderation after a crash is idempotent.
                offset = update["update_id"] + 1
                temporary = offset_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(offset), encoding="utf-8")
                temporary.replace(offset_file)
        except APIError as exc:
            if exc.code in {401, 409}:
                LOG.error("Остановка: проверьте токен и отсутствие второго экземпляра. %s", exc)
                return 1
            LOG.warning("Повтор после ошибки: %s", exc)
            time.sleep(max(3, exc.retry_after))


if __name__ == "__main__":
    try:
        instance_lock = acquire_instance_lock() if os.name == "nt" else None
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
    except (ValueError, OSError, APIError) as exc:
        print(f"Не удалось запустить бота: {exc}")
        raise SystemExit(1)
