from factcheck.models import Claim
from factcheck.verification import verify_claim

claim = Claim(id=1, text="The Earth is the third planet from the Sun.", page=1, category="general")
result = verify_claim(claim, max_sources=3)
print(result.method)
print(result.verdict)
print(result.confidence)
print(result.rationale)
