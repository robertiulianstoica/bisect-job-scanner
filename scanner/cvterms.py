"""The skills vocabulary shared by scanner/ats.py and scanner/gap.py.

Each term is (name, regex). The regex is matched case-insensitively against
plain text: an advert, or the text layer of a CV PDF. A term an advert asks
for and the CV never names is what an ATS keyword filter would miss.

Add a term here when an advert asks for something the list does not know;
both tools pick it up.
"""

from __future__ import annotations

import re

TERMS: list[tuple[str, str]] = [
    # languages
    ("PHP", r"\bphp\b"),
    ("JavaScript", r"\bjavascript\b|\bjs\b"),
    ("TypeScript", r"\btypescript\b"),
    ("Python", r"\bpython\b"),
    ("Go", r"\bgolang\b|\bgo\s+(?:language|developer|services|microservices)\b|\(go\)|\bgo,|\bin go\b"),
    ("Java", r"\bjava\b(?!\s*script)"),
    ("Kotlin", r"\bkotlin\b"),
    ("C#/.NET", r"\bc#|(?<![\w])\.net\b"),
    ("Ruby/Rails", r"\bruby\b|\brails\b"),
    ("Rust", r"\brust\b"),
    ("SQL", r"\bsql\b"),
    # PHP ecosystem
    ("Symfony", r"\bsymfony\b"),
    ("Laravel", r"\blaravel\b"),
    ("Doctrine", r"\bdoctrine\b"),
    ("Twig", r"\btwig\b"),
    ("Composer", r"\bcomposer\b"),
    ("PHPUnit", r"\bphpunit\b"),
    ("PHPStan/Psalm", r"\bphpstan\b|\bpsalm\b"),
    ("Pest", r"\bpest(?:php)?\b"),
    ("Livewire", r"\blivewire\b"),
    ("Inertia", r"\binertia(?:\.js)?\b"),
    ("API Platform", r"\bapi platform\b"),
    ("Phalcon", r"\bphalcon\b"),
    ("Yii", r"\byii2?\b"),
    ("Zend/Laminas", r"\bzend\b|\blaminas\b"),
    ("CodeIgniter", r"\bcodeigniter\b|\bcode igniter\b"),
    # e-commerce and CMS
    ("Magento/Adobe Commerce", r"\bmagento\b|\badobe commerce\b"),
    ("Shopware", r"\bshopware\b"),
    ("Shopify", r"\bshopify\b"),
    ("WooCommerce", r"\bwoocommerce\b"),
    ("WordPress", r"\bwordpress\b"),
    ("Drupal", r"\bdrupal\b"),
    ("PrestaShop", r"\bprestashop\b"),
    ("Sylius", r"\bsylius\b"),
    ("Akeneo/PIM", r"\bakeneo\b|\bpim\b"),
    ("Hyvä", r"\bhyv[aä]\b"),
    # frontend
    ("React", r"\breact(?:\.js|js)?\b(?!\s*native)"),
    ("React Native", r"\breact native\b"),
    ("Vue", r"\bvue(?:\.js|js)?\b"),
    ("Nuxt", r"\bnuxt\b"),
    ("Next.js", r"\bnext\.?js\b"),
    ("Angular", r"\bangular\b"),
    ("Svelte", r"\bsvelte\b"),
    ("Tailwind", r"\btailwind\b"),
    ("SCSS/Sass", r"\bs[ac]ss\b"),
    ("Vite", r"\bvite\b"),
    ("Webpack", r"\bwebpack\b"),
    ("Storybook", r"\bstorybook\b"),
    ("jQuery", r"\bjquery\b"),
    ("Node.js", r"\bnode(?:\.js|js)?\b"),
    ("NestJS", r"\bnest\.?js\b"),
    ("Express", r"\bexpress(?:\.js|js)\b"),
    # data
    ("MySQL/MariaDB", r"\bmysql\b|\bmariadb\b"),
    ("PostgreSQL", r"\bpostgres(?:ql)?\b"),
    ("MongoDB", r"\bmongo(?:db)?\b"),
    ("Redis", r"\bredis\b"),
    ("Elasticsearch/OpenSearch", r"\belastic\s?search\b|\bopensearch\b"),
    ("ClickHouse", r"\bclickhouse\b"),
    ("BigQuery", r"\bbigquery\b"),
    ("Snowflake", r"\bsnowflake\b"),
    ("DynamoDB", r"\bdynamodb\b"),
    ("Kafka", r"\bkafka\b"),
    ("RabbitMQ", r"\brabbitmq\b"),
    ("SQS/SNS", r"\bsqs\b|\bsns\b"),
    ("Message queues", r"\bmessage queues?\b|\bmessage broker\b|\bmessenger\b"),
    ("Event-driven", r"\bevent[- ]driven\b|\bevent sourcing\b"),
    ("Varnish", r"\bvarnish\b"),
    # infrastructure
    ("Docker", r"\bdocker\b"),
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b|\bhelm\b"),
    ("Terraform/IaC", r"\bterraform\b|\binfrastructure as code\b|\biac\b|\bpulumi\b"),
    ("AWS", r"\baws\b|\bamazon web services\b"),
    ("GCP", r"\bgcp\b|\bgoogle cloud\b"),
    ("Azure", r"\bazure\b"),
    ("Linux", r"\blinux\b"),
    ("Nginx", r"\bnginx\b"),
    ("CI/CD", r"\bci/?cd\b|\bcontinuous (?:integration|delivery|deployment)\b"),
    ("GitHub Actions", r"\bgithub actions\b"),
    ("GitLab CI", r"\bgitlab(?:[- ]ci)?\b"),
    ("Jenkins", r"\bjenkins\b"),
    ("Serverless/Lambda", r"\bserverless\b|\blambda\b"),
    ("Observability", r"\bobservability\b|\bopentelemetry\b|\bprometheus\b|\bgrafana\b|\bdatadog\b|\bnew relic\b|\bsentry\b"),
    # architecture and practice
    ("Microservices", r"\bmicro-?services?\b"),
    ("REST APIs", r"\brest(?:ful)?\b"),
    ("GraphQL", r"\bgraphql\b"),
    ("gRPC", r"\bgrpc\b"),
    ("OpenAPI/Swagger", r"\bopenapi\b|\bswagger\b"),
    ("DDD", r"\bddd\b|\bdomain[- ]driven\b"),
    ("CQRS", r"\bcqrs\b"),
    ("Hexagonal/Clean architecture", r"\bhexagonal\b|\bclean architecture\b|\bports and adapters\b"),
    ("SOLID", r"\bsolid\b"),
    ("Design patterns", r"\bdesign patterns?\b"),
    ("TDD", r"\btdd\b|\btest[- ]driven\b"),
    ("E2E testing", r"\bplaywright\b|\bcypress\b|\bselenium\b|\bbehat\b|\bcodeception\b"),
    ("Code review", r"\bcode reviews?\b"),
    ("Mentoring", r"\bmentor\w*|\bcoach(?:ing|ed)?\b"),
    ("Technical leadership", r"\btech(?:nical)? lead\b|\btechnical leadership\b"),
    ("System design", r"\bsystem design\b|\bsoftware architecture\b"),
    ("Performance optimisation", r"\bperformance (?:optimi[sz]ation|tuning)\b|\bcore web vitals\b"),
    ("Security/OWASP", r"\bowasp\b|\bsecurity best practices\b|\bsecure coding\b"),
    ("OAuth/SSO", r"\boauth\b|\bsso\b|\bsaml\b|\bopenid\b|\bjwt\b"),
    ("Payments", r"\bpayments?\b|\bstripe\b|\badyen\b|\bpaypal\b|\bcheckout\b"),
    ("Integrations/third-party APIs", r"\bintegrations?\b|\bthird[- ]party apis?\b"),
    ("Legacy modernisation", r"\blegacy\b|\bmigrations?\b|\bmoderni[sz]"),
    ("A/B testing", r"\ba/b test|\bexperimentation\b|\bfeature flags?\b"),
    ("Agile/Scrum", r"\bagile\b|\bscrum\b|\bkanban\b"),
    # AI
    ("LLM/GenAI", r"\bllms?\b|\bgenai\b|\bgenerative ai\b|\blarge language models?\b"),
    ("AI coding tools", r"\bcopilot\b|\bcursor\b|\bclaude\b|\bai[- ]assisted\b|\bai tools\b"),
    ("RAG/vector DB", r"\brag\b|\bvector (?:db|database|search)\b|\bembeddings?\b|\bpgvector\b"),
    ("MCP", r"\bmcp\b|\bmodel context protocol\b"),
    ("AI agents", r"\bagentic\b|\bai agents?\b|\bagents\b"),
    # languages spoken
    ("German", r"\bgerman\b|\bdeutsch\b"),
    ("French", r"\bfrench\b"),
    ("Spanish", r"\bspanish\b"),
    ("Polish", r"\bpolish\b"),
    ("Dutch", r"\bdutch\b"),
]

COMPILED = [(name, re.compile(rx, re.I)) for name, rx in TERMS]


def found(text: str) -> set[str]:
    """The vocabulary terms that appear in the text."""
    return {name for name, rx in COMPILED if rx.search(text)}


def count(text: str, name: str) -> int:
    rx = dict(COMPILED)[name]
    return len(rx.findall(text))
