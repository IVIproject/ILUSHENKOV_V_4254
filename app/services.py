import json
import re
from pathlib import Path
from typing import Any


def normalize_zone(zone: str) -> str:
    z = zone.strip().lower()
    if not z.startswith("."):
        z = "." + z
    return z


def _extract_json_object(raw: str) -> dict[str, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    result: dict[str, str] = {}
    if isinstance(parsed, dict):
        for k, v in parsed.items():
            if isinstance(k, str):
                result[k] = str(v)
    return result


def _template_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "pages"


def render_named_php_template(
    client: Any,
    model: str,
    template_name: str,
    content_prompt: str,
) -> tuple[str, str]:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", template_name)
    if not safe_name:
        raise ValueError("Invalid template_name")
    template_path = _template_root() / f"{safe_name}.php"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {safe_name}.php")

    template_text = template_path.read_text(encoding="utf-8")
    placeholders = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", template_text)))
    if not placeholders:
        return template_text, f"{safe_name}-generated.php"

    prompt = (
        "You are generating content for a PHP page template.\n"
        "Return ONLY valid JSON object with values for placeholders.\n"
        "Do not include markdown, comments, or code fences.\n"
        "Keep answers concise and suitable for website page copy.\n"
        f"Task: {content_prompt}\n"
        f"Placeholders: {', '.join(placeholders)}\n"
    )
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp["message"]["content"]
    replacements = _extract_json_object(raw)

    fallback_text = content_prompt.strip() or "Content will be provided later."
    rendered = template_text
    for key in placeholders:
        value = replacements.get(key, fallback_text)
        rendered = rendered.replace(f"{{{{{key}}}}}", value)

    return rendered, f"{safe_name}-generated.php"


def _parse_domain_candidates(raw_text: str, zone: str, count: int) -> list[str]:
    candidates: list[str] = []
    for line in raw_text.splitlines():
        cleaned = line.strip().strip("-").strip()
        if not cleaned or "." not in cleaned or " " in cleaned:
            continue
        normalized = cleaned.lower()
        if not normalized.endswith(zone):
            continue
        candidates.append(normalized)

    unique = list(dict.fromkeys(candidates))[:count]
    return unique


def run_chat_mode(
    client: Any,
    model: str,
    prompt: str,
) -> str:
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp["message"]["content"]


def run_domain_mode(
    client: Any,
    model: str,
    business_context: str,
    keywords: list[str],
    zone: str,
    count: int,
) -> str:
    safe_zone = normalize_zone(zone)
    mode_prompt = (
        "Generate ONLY domain names, one per line, no numbering, no comments, no explanations.\n"
        f"Requested count: {count}\n"
        f"Domain zone: {safe_zone}\n"
        "Use only latin letters, digits, and hyphen.\n"
        f"Business context: {business_context}\n"
        f"Keywords: {', '.join(keywords) if keywords else 'none'}\n"
    )
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": mode_prompt}],
    )
    return resp["message"]["content"]


def _inject_text_into_template(template: str, content: str) -> str:
    placeholders = [
        "{{content}}",
        "[[content]]",
        "<!--CONTENT-->",
    ]
    for ph in placeholders:
        if ph in template:
            return template.replace(ph, content)

    if "</body>" in template.lower():
        idx = template.lower().rfind("</body>")
        return template[:idx] + "<main>\n" + content + "\n</main>\n" + template[idx:]

    return template + "\n\n" + content


def render_php_template(
    client: Any,
    model: str,
    template_html: str,
    prompt: str,
) -> str:
    text_prompt = (
        "Generate ONLY page text content for this task.\n"
        "Do not include HTML, CSS, JS, comments, or markdown.\n"
        "Output plain text paragraphs.\n"
        f"Task: {prompt}"
    )
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": text_prompt}],
    )
    content_text = resp["message"]["content"].strip()
    return _inject_text_into_template(template_html, content_text)


def extract_domain_suggestions(raw_text: str, zone: str, count: int) -> list[str]:
    safe_zone = normalize_zone(zone)
    domains = _parse_domain_candidates(raw_text, safe_zone, count)
    return domains[:count]


def run_support_faq_mode(
    client: Any,
    model: str,
    user_question: str,
    faq_pairs: list[tuple[str, str]],
) -> str:
    faq_context = (
        "\n\n".join(f"Q: {q}\nA: {a}" for q, a in faq_pairs)
        if faq_pairs
        else "No FAQ context available."
    )
    composed_prompt = (
        "You are a technical support assistant for domain registration and hosting.\n"
        "Answer using FAQ style: concise, practical, and clear.\n"
        f"Client question: {user_question}\n\n"
        f"FAQ context:\n{faq_context}\n"
    )
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": composed_prompt}],
    )
    return resp["message"]["content"]


def _tokenize_for_relevance(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Zа-яА-Я0-9]+", text.lower())
    return {token for token in tokens if len(token) >= 3}


def select_relevant_faq_pairs(
    user_question: str,
    faq_pairs: list[tuple[str, str]],
    max_items: int,
) -> list[tuple[str, str]]:
    question_tokens = _tokenize_for_relevance(user_question)
    if not faq_pairs:
        return []

    scored: list[tuple[int, int, tuple[str, str]]] = []
    for index, pair in enumerate(faq_pairs):
        q, a = pair
        pair_tokens = _tokenize_for_relevance(f"{q} {a}")
        score = len(question_tokens.intersection(pair_tokens))
        scored.append((score, index, pair))

    ranked = sorted(
        scored,
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    selected: list[tuple[str, str]] = []
    for score, _, pair in ranked:
        if score <= 0 and selected:
            continue
        selected.append(pair)
        if len(selected) >= max_items:
            break

    if selected:
        return selected
    return faq_pairs[:max_items]


def extract_support_faq_pairs(transcript: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lower().startswith("q:"):
            question = line[2:].strip()
            answer = ""
            if i + 1 < len(lines) and lines[i + 1].lower().startswith("a:"):
                answer = lines[i + 1][2:].strip()
                i += 1
            if question and answer:
                pairs.append((question, answer))
        i += 1

    if pairs:
        return pairs

    # Fallback: split by dialog-like separators "Client:" / "Support:"
    question = None
    for line in lines:
        lower = line.lower()
        if lower.startswith("client:") or lower.startswith("клиент:"):
            question = line.split(":", 1)[1].strip()
        elif lower.startswith("support:") or lower.startswith("поддержка:"):
            answer = line.split(":", 1)[1].strip()
            if question and answer:
                pairs.append((question, answer))
                question = None
    return pairs
