from pathlib import Path


def normalize_template_name(name: str) -> str:
    return name.replace("\\", "/").strip().split("/")[-1]


def load_template(template_name: str) -> str:
    safe_name = normalize_template_name(template_name)
    path = Path("templates/pages") / safe_name
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Template not found: {safe_name}")
    return path.read_text(encoding="utf-8")


def build_hosting_template_from_source(source_php: str) -> str:
    # Minimal deterministic transformation from source page into template placeholders.
    # Product-related blocks are wrapped into protected markers and should not be modified.
    text = source_php

    replacements = {
        '$title="HOSTING.PRO";': '$title="{{AI_TITLE}}";',
        '$description="Netplace.ru - Надежный и доступный хостинг для вашего бизнеса. Безопасность, скорость и круглосуточная поддержка!";':
            '$description="{{AI_META_DESCRIPTION}}";',
        '$keywords="Хостинг, eco-hosting, эконом-класс, виртуальный хостинг эконом класса, недорогой виртуальный хостинг";':
            '$keywords="{{AI_META_KEYWORDS}}";',
        '<div class="title-h4 whites">Web-хостинг для сайтов</div>':
            '<div class="title-h4 whites">{{AI_HERO_TITLE}}</div>',
        '<p class="service greys">Мы обеспечиваем бесперебойную круглосуточную работу веб-сайта. Виртуальный хостинг имеет удобную панель управления на ваш вкус: <b>cPanel, DirectAdmin или ISP Manager</b>. При заказе есть возможность выбрать конкретный сервер, на котором будет размещаться сайт. Таким образом, можно выбрать панель управления и страну размещения сервера. Круглосуточная техническая поддержка всегда готова ответить на ваши вопросы и помочь в решении вопросов по сайту.</p>':
            '<p class="service greys">{{AI_HERO_TEXT}}</p>',
        '<div class="title-h4 whites">Преимущества HOSTING.PRO</div>':
            '<div class="title-h4 whites">{{AI_ADVANTAGES_TITLE}}</div>',
        '<div class="title-h4 whites">Информация для Вас</div>':
            '<div class="title-h4 whites">{{AI_INFO_TITLE}}</div>',
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    def _wrap_block(start_marker: str, end_marker: str, label: str) -> str:
        nonlocal text
        s = text.find(start_marker)
        if s == -1:
            return text
        e = text.find(end_marker, s)
        if e == -1:
            return text
        e += len(end_marker)
        block = text[s:e]
        wrapped = (
            f"<!-- {label}_START -->\n"
            + block
            + f"\n<!-- {label}_END -->"
        )
        text = text[:s] + wrapped + text[e:]
        return text

    _wrap_block(
        '<div id="testimonials-list" class="owl-carousel">',
        "</div>",
        "AI_PROTECTED_PRODUCTS",
    )
    _wrap_block(
        '<div id="testimonials-list-server" class="owl-carousel">',
        "</div>",
        "AI_PROTECTED_SERVER_PRODUCTS",
    )

    return text


def generate_hosting_page_from_template(
    client,
    model: str,
    template_text: str,
    content_prompt: str,
) -> str:
    import json
    import re

    placeholders = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", template_text)))
    if not placeholders:
        return template_text

    prompt = (
        "You generate Russian marketing/support copy for hosting pages.\n"
        "Return ONLY valid JSON with keys equal to provided placeholders.\n"
        "Do not add extra keys, markdown, comments or code fences.\n"
        f"Task: {content_prompt}\n"
        f"Placeholders: {', '.join(placeholders)}\n"
    )

    resp = client.chat(model=model, messages=[{"role": "user", "content": prompt}])
    raw = resp["message"]["content"].strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

    data = {}
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(raw[start:end + 1])
    except Exception:
        data = {}

    result = template_text
    fallback = "Контент будет добавлен позднее."
    for key in placeholders:
        value = str(data.get(key, fallback))
        result = result.replace(f"{{{{{key}}}}}", value)
    return result

