import re
import string
from pathlib import Path

from langtrainer import i18n

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "langtrainer" / "web" / "templates"


def test_every_language_has_the_same_keys():
    keys = {lang: set(strings) for lang, strings in i18n.STRINGS.items()}
    assert keys["ru"] == keys["en"]


def test_placeholders_match_between_languages():
    def fields(text):
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    for key, en in i18n.STRINGS["en"].items():
        assert fields(en) == fields(i18n.STRINGS["ru"][key]), key


def test_every_key_used_in_templates_exists():
    used = set()
    for path in TEMPLATES.glob("*.html"):
        used |= set(re.findall(r"\bt\('([\w.]+)'\s*[,)]", path.read_text()))
    assert used, "no t() calls found"
    assert used <= set(i18n.STRINGS["en"]), used - set(i18n.STRINGS["en"])


def test_dynamic_prefixes_are_covered():
    for prefix in ("status", "cat", "rate", "wait"):
        assert any(k.startswith(prefix + ".") for k in i18n.STRINGS["en"])


def test_templates_have_no_hardcoded_cyrillic():
    for path in TEMPLATES.glob("*.html"):
        assert not re.search("[А-Яа-я]", path.read_text()), path.name


def test_translate_with_values_and_fallbacks():
    assert i18n.translate("en", "wait.days", n=3) == "in 3 d"
    assert i18n.translate("ru", "wait.days", n=3) == "через 3 дн."
    assert i18n.translate("fr", "nav.talks") == "Conversations"
    assert i18n.translate("en", "no.such.key") == "no.such.key"
    assert i18n.translate_value("ru", "status", "done") == "готово"
    assert i18n.translate_value("ru", "cat", "something_new") == "something_new"


def test_pick_language_order():
    assert i18n.pick_language("ru", "en-US") == "ru"
    assert i18n.pick_language(None, "ru-RU,ru;q=0.9,en;q=0.8") == "ru"
    assert i18n.pick_language("xx", "fr-FR,en;q=0.5") == "en"
    assert i18n.pick_language(None, None) == i18n.DEFAULT_LANG
