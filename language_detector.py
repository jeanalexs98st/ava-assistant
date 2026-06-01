import re

# Words/patterns that strongly indicate Portuguese (not Spanish)
PT_SIGNALS = [
    "não", "voce", "você", "também", "tambem", "gastei", "paguei", "recebi",
    "comprei", "ganhei", "minha", "minhas", "nosso", "nossa", "muito", "pouco",
    "ainda", "agora", "porque", "então", "entao", "obrigado", "obrigada",
    "oi", "ola", "olá", "tudo bem", "tô", "to bem", "né", "né", "tá", "ta",
    "extrato", "saldo", "resumo", "relatorio", "relatório", "ajuda", "conselho",
    "orçamento", "orcamento", "desfazer", "apagar", "últimos", "ultimos",
    "finanças", "financas", "renda", "salario", "salário", "almoço", "almoco",
    "jantar", "padaria", "mercado", "farmacia", "farmácia", "academia",
    "onibus", "ônibus", "passagem", "gasolina", "aluguel", "conta",
]

# Words/patterns that strongly indicate Spanish (not Portuguese)
ES_SIGNALS = [
    "hola", "gracias", "buenos", "buenas", "como estas", "cómo estás",
    "también", "también", "ahora", "gasté", "gaste", "pagué", "pague",
    "recibí", "recibi", "gané", "gane", "cobré", "cobre",
    "mis ", "mío", "mia", "nuestro", "nuestra", "mucho", "poco", "todavía",
    "todavia", "porque", "entonces", "gracias", "resumen", "reporte",
    "presupuesto", "deshacer", "últimas", "ultimas", "finanzas", "sueldo",
    "almuerzo", "cena", "desayuno", "farmacia", "gimnasio", "transporte",
    "boleta", "factura", "arriendo", "ingreso", "consejo", "ayuda",
]

# Portuguese-only characters/patterns
PT_CHARS = re.compile(r"[ãõê]|ção|ções|ão\b")

# Spanish-only characters/patterns
ES_CHARS = re.compile(r"ñ|¿|¡|ción\b|ciones\b")


def detect_language(text: str) -> str | None:
    """
    Returns 'pt', 'es', or 'en' if confident, or None if uncertain.
    """
    lower = text.lower()

    pt_score = 0
    es_score = 0

    # Character-level signals (high confidence)
    if PT_CHARS.search(lower):
        pt_score += 3
    if ES_CHARS.search(lower):
        es_score += 3

    # Word-level signals
    for word in PT_SIGNALS:
        if word in lower:
            pt_score += 2

    for word in ES_SIGNALS:
        if word in lower:
            es_score += 2

    # Need a minimum score to be confident
    if pt_score == 0 and es_score == 0:
        return None  # Can't tell — keep current language

    if pt_score > es_score:
        return "pt"
    elif es_score > pt_score:
        return "es"
    else:
        return None  # Tie — keep current language
