from factcheck.models import Claim
from factcheck.verification import _heuristic_assessment
from factcheck.web_search import build_queries, reliability_score, search_web

claims = [
    "The global internet population exceeded 10 billion people in 2024.",
    "The World Health Organization was founded in 1948.",
]
for index, text in enumerate(claims, 1):
    claim = Claim(id=index, text=text, page=1, category="statistical")
    queries = build_queries(text)
    sources = search_web(queries, max_results=5)
    print("CLAIM", text)
    print("QUERIES", queries)
    for source in sources:
        print(f"SOURCE {source.domain} reliability={reliability_score(source):.2f} title={source.title}")
        print("SNIPPET", source.snippet)
    result = _heuristic_assessment(claim, sources, queries)
    print("RESULT", result.verdict, result.confidence, result.rationale)
