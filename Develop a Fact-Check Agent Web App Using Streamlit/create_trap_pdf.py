from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

output = Path('/home/ubuntu/fact_check_agent/tests/trap_document.pdf')
pdf = canvas.Canvas(str(output), pagesize=A4)
pdf.setTitle('FactCheck Agent Trap Document')
pdf.setFont('Helvetica-Bold', 16)
pdf.drawString(72, 780, 'Trap Document: Digital Economy Claims')
pdf.setFont('Helvetica', 11)
lines = [
    'The Earth is the third planet from the Sun.',
    'The global internet population exceeded 10 billion people in 2024.',
    'The World Health Organization was founded in 1948.',
]
for index, line in enumerate(lines):
    pdf.drawString(72, 735 - index * 28, line)
pdf.save()
print(output)
