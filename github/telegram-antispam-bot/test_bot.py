import unittest

from bot import APIError, Moderator
from spam_filter import classify


SPAM = [
    "Кто свободен вписаться в одну тему? По итогу отдаю нал по выполнению",
    "Здравствуйте! Ищу на завтра 5 человек на под работку, если понравиться, могу взять на постоянную основу, 4000 за 3 часа",
    "Доброе утро, на сегодня и завтра надо 2 чел, на руки 6к каждому",
    "Всем привет. На сейчас нужно пару человек для помощи, не чего сложного плачу 5500. Есть кто",
    "Ищем людей на подрaботку. Без опыта, 5000 за 2 часа, пишите в личку",
    "Нужны люди на под\u200bработку, оплата 5 000 рублей",
]

NEW_SPAM = [
    "Есть несложные задачи в сфере криптовалют. Обучаем бесплатно с нуля, куратор всегда на связи. Все подробности можно узнать у @spam_contact_hr.",
    "Ищу людей в бизнес в сфере криптовалюты. Детали: @other_contact_hr",
    "Возьму 3 человек для совместного онлайн-дохода. Сфера — крипта. Если никогда этим не занимались — не проблема. За подробностями сюда: @spam_contact_hr",
    "Приветик всем, ищу человека кто сможет купить нам с девочками ящик мартини и принести на 5 этаж , 4к и бутылка за помощь.Есть тут кто сможет ?",
    "Приветик, ищу человека кто сможет купить нам с девочками ящик мартини и принести на 5 этаж , 4к и бутылка за помощь.Есть кто сможет ?",
    "Всем привет ,Нужны люди для покрасок лавочек у подъездов .каждому по 4700р. сразу на руки за пару часов. есть тут кто сможет ?",
    "Может кто-то знает контакты крипта-обменника или же сам продает? Ищу где купить можно за наличные",
    "оставить отзыв 1000р",
    "Кто свободен,и сможет помочь одинокой девушке с переездом ? плачу 9500",
    "Написать фидбек о услугах - 3000р",
]


class FakeAPI:
    def __init__(self, status="member", fail=None):
        self.status, self.fail, self.calls = status, fail, []

    def call(self, method, **data):
        self.calls.append((method, data))
        if method == self.fail:
            raise APIError(403, "Forbidden")
        if method == "getChatMember":
            return {"status": self.status}
        return True


def message(text=SPAM[1], **extra):
    return {"message_id": 8, "chat": {"id": -100123, "type": "supergroup"},
            "from": {"id": 123}, "text": text, **extra}


class FilterTests(unittest.TestCase):
    def test_new_examples(self):
        for text in NEW_SPAM:
            with self.subTest(text=text):
                self.assertTrue(classify(text).spam, classify(text))

    def test_new_normal_conversation(self):
        for text in [
            "Здравствуйте, чат", "Соня теперь в группе", "Что такое криптовалюта?",
            "Ищу людей для обсуждения криптовалюты", "Курс криптовалюты 1000р",
            "Подскажите адрес обменника, хочу поменять рубли на лари",
            "Кто поможет с переездом?", "Купите мартини и принесите на 5 этаж",
            "Ищу человека, который доставит продукты, бюджет 4000р",
            "Можно оставить отзыв об экскурсии?", "Экскурсия 3000р, отзывы у @guide_test",
            "Спасибо за отзыв! Вернули 1000р", "Обучаем с нуля игре на гитаре, @music_test",
        ]:
            with self.subTest(text=text):
                self.assertFalse(classify(text).spam, classify(text))

    def test_campaign_threshold_and_variations(self):
        for text in NEW_SPAM:
            self.assertFalse(classify(text, 100).spam)
        for text in ["Написать фидбэк — 3000₽", "Оставить отзыв 1000p",
                     "Ищу людей в сфере криптoвалюты. Детали: @another_contact",
                     "Есть несложные задачи в сфере криптовалют. Обучаем бесплатно с нуля. Пишите в лс"]:
            with self.subTest(text=text):
                self.assertTrue(classify(text).spam, classify(text))

    def test_examples(self):
        for text in SPAM:
            with self.subTest(text=text):
                self.assertTrue(classify(text).spam, classify(text))

    def test_normal_conversation(self):
        for text in ["Ищу работу программистом", "Кто завтра на работу?", "Ищу 5 человек для игры в футбол",
                     "Экскурсия стоит 4000 за 3 часа", "Оплата коммунальных услуг 5500",
                     "Ищу квартиру до 40000 рублей", "Спасибо за помощь!", "", "Пишите в личку"]:
            with self.subTest(text=text):
                self.assertFalse(classify(text).spam)

    def test_threshold(self):
        self.assertFalse(classify(SPAM[1], 100).spam)


class ModerationTests(unittest.TestCase):
    def test_new_examples_moderated(self):
        for text in NEW_SPAM:
            with self.subTest(text=text):
                calls = self.run_message(message(text))
                self.assertEqual([c[0] for c in calls], ["getChatMember", "deleteMessage", "banChatMember"])

    def run_message(self, msg=None, api=None, edited=False, **kwargs):
        api = api or FakeAPI()
        moderator = Moderator(api, {"id": 999, "username": "guardbot"}, **kwargs)
        moderator.handle({"edited_message" if edited else "message": msg or message()})
        return api.calls

    def test_delete_and_permanent_ban(self):
        calls = self.run_message()
        self.assertEqual([c[0] for c in calls], ["getChatMember", "deleteMessage", "banChatMember"])
        self.assertEqual(calls[-1][1], {"chat_id": -100123, "user_id": 123, "revoke_messages": True})

    def test_admin_exempt(self):
        for role in ("administrator", "creator"):
            self.assertEqual(len(self.run_message(api=FakeAPI(role))), 1)

    def test_lookup_failure_cannot_ban(self):
        api = FakeAPI(fail="getChatMember")
        with self.assertRaises(APIError):
            self.run_message(api=api)
        self.assertEqual(len(api.calls), 1)

    def test_ban_even_if_delete_fails(self):
        calls = self.run_message(api=FakeAPI(fail="deleteMessage"))
        self.assertEqual(calls[-1][0], "banChatMember")

    def test_dry_run(self):
        self.assertEqual(len(self.run_message(dry_run=True)), 1)

    def test_whitelist(self):
        self.assertEqual(self.run_message(whitelist={123}), [])

    def test_other_group(self):
        self.assertEqual(self.run_message(chats={-987}), [])

    def test_sender_chat(self):
        self.assertEqual(self.run_message(message(sender_chat={"id": -100123})), [])

    def test_private_chat(self):
        self.assertEqual(self.run_message(message(chat={"id": 123, "type": "private"})), [])

    def test_caption_and_edit(self):
        self.assertEqual(self.run_message(message(text="", caption=SPAM[1]), edited=True)[-1][0], "banChatMember")

    def test_command(self):
        self.assertEqual(self.run_message(message("/chatid@guardbot"))[0][0], "sendMessage")

    def test_service_update(self):
        api = FakeAPI()
        Moderator(api, {"id": 999}).handle({"my_chat_member": {}})
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
