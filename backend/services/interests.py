"""
Каталог интересов пользователя. Используется при регистрации и при автогенерации темы.
"""

# slug → human-readable label
INTERESTS: dict[str, str] = {
    "ai_agents":  "🤖 AI Agents & Multi-agent systems",
    "llm":        "🧠 LLMs & Foundation Models",
    "ml_ops":     "📊 Machine Learning / MLOps",
    "ai_infra":   "⚡ AI Infrastructure (GPU, inference)",
    "robotics":   "🦾 Robotics & Embodied AI",
    "crypto":     "₿  Crypto & Web3",
    "defi":       "💸 DeFi & Tokenomics",
    "cybersec":   "🛡 Cybersecurity",
    "devtools":   "🛠 Developer Tools & DX",
    "cloud":      "☁️ Cloud & DevOps",
    "data_eng":   "🗄 Data Engineering",
    "startups":   "🚀 Startups & VC",
}


def label(slug: str) -> str:
    return INTERESTS.get(slug, slug)


def all_slugs() -> list[str]:
    return list(INTERESTS.keys())
