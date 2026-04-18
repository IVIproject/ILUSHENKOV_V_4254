import re
from typing import Any


def normalize_zone(zone: str) -> str:
    z = zone.strip().lower()
    if not z.startswith("."):
        z = "." + z
    return z


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
