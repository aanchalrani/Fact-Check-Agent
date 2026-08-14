from pathlib import Path

from factcheck.pdf_utils import extract_claims, extract_pdf_text
from factcheck.verification import verify_claim

pdf_bytes = Path('/home/ubuntu/fact_check_agent/tests/trap_document.pdf').read_bytes()
text, pages, page_map = extract_pdf_text(pdf_bytes)
claims = extract_claims(page_map, use_llm=False, max_claims=8)
print(f'pages={pages} claims={len(claims)} chars={len(text)}')
for claim in claims:
    result = verify_claim(claim, max_sources=3)
    print(f'{claim.id}\t{result.verdict}\t{result.confidence:.2f}\t{claim.text}')
    print('  sources:', ', '.join(source.domain for source in result.sources))
