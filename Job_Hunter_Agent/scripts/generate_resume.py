"""Renders profile/resume_content.yaml into assets/Adar_Rubin_CV.pdf.

Run standalone: python scripts/generate_resume.py [content_yaml] [output_pdf]
Defaults to profile/resume_content.yaml -> assets/Adar_Rubin_CV.pdf.

The real content file is gitignored (see .gitignore) and, in CI, is restored at runtime
from the RESUME_CONTENT_YAML secret -- see profile/resume_content.example.yaml for the schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTENT = PROJECT_ROOT / "profile" / "resume_content.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "assets" / "Adar_Rubin_CV.pdf"

_NAME = ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=20, spaceAfter=2)
_HEADLINE = ParagraphStyle("headline", fontName="Helvetica", fontSize=11, textColor="#444444", spaceAfter=4)
_CONTACT = ParagraphStyle("contact", fontName="Helvetica", fontSize=9, textColor="#444444", spaceAfter=12)
_SECTION = ParagraphStyle(
    "section", fontName="Helvetica-Bold", fontSize=12, spaceBefore=10, spaceAfter=4,
    borderPadding=0,
)
_ENTRY_TITLE = ParagraphStyle("entry_title", fontName="Helvetica-Bold", fontSize=10, spaceAfter=1)
_ENTRY_SUB = ParagraphStyle("entry_sub", fontName="Helvetica-Oblique", fontSize=9.5, spaceAfter=3)
_BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13, spaceAfter=6)
_BULLET = ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.5, leading=13, leftIndent=12)


def _load_content(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_story(content: dict) -> list:
    story = [
        Paragraph(content["name"], _NAME),
        Paragraph(content.get("headline", ""), _HEADLINE),
    ]

    contact = content.get("contact", {})
    contact_bits = [contact.get("email", ""), contact.get("phone", ""), contact.get("location", "")]
    contact_bits.extend(contact.get("links", []))
    story.append(Paragraph(" | ".join(b for b in contact_bits if b), _CONTACT))

    if content.get("summary"):
        story.append(Paragraph(content["summary"].strip(), _BODY))

    if content.get("experience"):
        story.append(Paragraph("EXPERIENCE", _SECTION))
        for job in content["experience"]:
            story.append(Paragraph(f"{job['title']} - {job['company']}", _ENTRY_TITLE))
            story.append(Paragraph(job.get("dates", ""), _ENTRY_SUB))
            for bullet in job.get("bullets", []):
                story.append(Paragraph(f"&bull; {bullet}", _BULLET))
            story.append(Spacer(1, 4))

    if content.get("education"):
        story.append(Paragraph("EDUCATION", _SECTION))
        for edu in content["education"]:
            story.append(Paragraph(edu["degree"], _ENTRY_TITLE))
            story.append(Paragraph(f"{edu['institution']} - {edu.get('dates', '')}", _ENTRY_SUB))

    if content.get("skills"):
        story.append(Paragraph("SKILLS", _SECTION))
        story.append(Paragraph(", ".join(content["skills"]), _BODY))

    if content.get("projects"):
        story.append(Paragraph("PROJECTS", _SECTION))
        for proj in content["projects"]:
            story.append(Paragraph(proj["name"], _ENTRY_TITLE))
            story.append(Paragraph(proj.get("description", ""), _BODY))

    return story


def generate(content_path: Path = DEFAULT_CONTENT, output_path: Path = DEFAULT_OUTPUT) -> None:
    content = _load_content(content_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
    )
    doc.build(_build_story(content))


if __name__ == "__main__":
    content_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONTENT
    output_arg = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    generate(content_arg, output_arg)
    print(f"Generated {output_arg}")
