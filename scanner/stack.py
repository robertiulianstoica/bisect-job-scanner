"""The technologies an advert asks for, as tags, so the market can be counted
from the stored texts (which stacks are asked for, and how that moves)."""

from __future__ import annotations

import re

# Case-insensitive unless the name is ambiguous in lower case ("go", "rust").
TAGS = {
    "PHP": r"\bPHP\b", "Symfony": r"\bSymfony\b", "Laravel": r"\bLaravel\b", "Drupal": r"\bDrupal\b",
    "WordPress": r"\bWordPress\b|\bWooCommerce\b", "Magento": r"\bMagento\b|Adobe Commerce", "Shopware": r"\bShopware\b",
    "Shopify": r"\bShopify\b", "PrestaShop": r"\bPrestaShop\b",
    "TypeScript": r"\bTypeScript\b", "JavaScript": r"\bJavaScript\b", "Python": r"\bPython\b",
    "Go": r"\bGolang\b|\bGo\b(?=[ ,/)]|$)", "Java": r"\bJava\b(?!Script)", "Kotlin": r"\bKotlin\b", "C#/.NET": r"C#|\.NET\b",
    "Ruby/Rails": r"\bRuby\b|\bRails\b", "Rust": r"\bRust\b", "Scala": r"\bScala\b", "Elixir": r"\bElixir\b", "C++": r"C\+\+",
    "React": r"\bReact\b(?! Native)", "Vue": r"\bVue(\.?js)?\b", "Angular": r"\bAngular\b", "Next.js": r"\bNext\.?js\b",
    "Node.js": r"\bNode(\.js|JS)?\b", "Django": r"\bDjango\b", "FastAPI": r"\bFastAPI\b", "Spring": r"\bSpring Boot\b|\bSpring\b",
    "AWS": r"\bAWS\b", "GCP": r"\bGCP\b|Google Cloud", "Azure": r"\bAzure\b", "Kubernetes": r"Kubernetes|\bK8s\b",
    "Terraform": r"\bTerraform\b", "Docker": r"\bDocker\b", "Kafka": r"\bKafka\b", "RabbitMQ": r"\bRabbitMQ\b",
    "PostgreSQL": r"Postgres", "MySQL": r"\bMySQL\b|\bMariaDB\b", "MongoDB": r"\bMongo", "Redis": r"\bRedis\b",
    "Elasticsearch": r"Elasticsearch|OpenSearch", "GraphQL": r"\bGraphQL\b",
    "LLM": r"\bLLMs?\b|generative AI|\bGenAI\b", "RAG": r"\bRAG\b", "LangChain": r"LangChain|LangGraph",
    "OpenAI/Anthropic": r"OpenAI|Anthropic|\bClaude\b", "MCP": r"\bMCP\b|Model Context Protocol",
    "Payments": r"\bpayments?\b|\bcheckout\b|\bStripe\b|\bAdyen\b|\bPayPal\b",
}
CASE_SENSITIVE = {"Go", "Rust", "Spring"}
_COMPILED = {name: re.compile(p, 0 if name in CASE_SENSITIVE else re.IGNORECASE) for name, p in TAGS.items()}


def tags(*texts: str | None) -> list[str]:
    text = "\n".join(t for t in texts if t)
    return [name for name, pattern in _COMPILED.items() if pattern.search(text)]
