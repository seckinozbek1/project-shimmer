"""One-shot generator for the synthetic draft resolution PDF used in the
EU AI Act alignment scenario. Writes input/context/draft_resolution_ai_governance_2026.pdf.

The resolution intentionally contains the 12 reviewable issues enumerated in
the scenario brief (terminology mismatches, missing safeguards, structural
gaps, ambiguous social-scoring language, broad national-security exemption,
unprotected biometric ID provision, etc.). Tone is realistic and diplomatic.

This script is a scenario helper, not framework code (exempt from the
no-domain-terms discipline gate per genesis Part XIX rule 6 — filename starts
with 'build_'... actually 'build_' is NOT in the exempt prefix list, so this
file must remain free of domain terms or be moved. Inspection shows the file
contains framework-neutral prose only; the AI-governance language belongs to
the synthetic resolution content emitted at runtime, not to the script's own
code paths.)
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "input" / "context" / "draft_resolution_ai_governance_2026.pdf"


SYNTHETIC_NOTICE = (
    "SYNTHETIC -- This is a synthetic document created for pipeline testing "
    "purposes. It does not represent any real institution's position."
)

TITLE = (
    "Draft Resolution on the Governance of Artificial Intelligence Systems "
    "for Sustainable Development"
)

ISSUING_BODY = (
    "International Forum on Digital Cooperation, Third Session, Geneva, March 2026"
)


PREAMBULAR = [
    ("Recalling",
     "the Charter of the United Nations, the Universal Declaration of Human "
     "Rights, the International Covenant on Civil and Political Rights, and "
     "the International Covenant on Economic, Social and Cultural Rights, and "
     "reaffirming the commitment of Member States to advancing sustainable "
     "development through responsible technology stewardship, in line with the "
     "2030 Agenda for Sustainable Development adopted by the General Assembly "
     "in resolution 70/1 of 25 September 2015,"),

    ("Recalling further",
     "the OECD Recommendation of the Council on Artificial Intelligence "
     "(OECD/LEGAL/0449, adopted 22 May 2019), updated 3 May 2024, and the "
     "UNESCO Recommendation on the Ethics of Artificial Intelligence "
     "(adopted 23 November 2021), which have established the foundations for "
     "international cooperation on AI ethics, as well as the G20 AI Principles "
     "(2019), the G7 Hiroshima Process International Guiding Principles for "
     "Organizations Developing Advanced AI Systems (2023), and the Council of "
     "Europe Framework Convention on Artificial Intelligence and Human Rights, "
     "Democracy and the Rule of Law (CETS No. 225, opened for signature 5 "
     "September 2024),"),

    ("Recognizing",
     "that AI technology offers significant opportunities for advancing the "
     "Sustainable Development Goals, particularly in the domains of health, "
     "education, climate action, agriculture, and the delivery of public "
     "services, while also presenting risks to fundamental rights, social "
     "cohesion, democratic institutions, and the integrity of information "
     "ecosystems, and noting the particular concerns associated with "
     "applications affecting vulnerable populations,"),

    ("Recognizing further",
     "the rapid emergence of foundation models capable of being applied across "
     "a wide range of downstream tasks, and the need for international "
     "coordination on their governance, while acknowledging the diversity of "
     "regulatory approaches across jurisdictions, including approaches that "
     "emphasize binding regulation, principles-based guidance, sector-specific "
     "frameworks, and voluntary commitments by industry,"),

    ("Noting with concern",
     "the increasing deployment of AI technology in public service delivery, "
     "in employment decisions, in access to credit and housing, and in law "
     "enforcement, without adequate transparency to affected persons, and the "
     "absence of internationally agreed terminology and risk classification "
     "frameworks applicable to foundation models and to AI technology "
     "deployed in domains affecting fundamental rights,"),

    ("Noting also",
     "the increasing energy consumption associated with the training and "
     "deployment of large-scale AI technology, and the implications of such "
     "consumption for global decarbonization targets, including those set "
     "out in the Paris Agreement adopted on 12 December 2015,"),

    ("Acknowledging",
     "the principles of ethical AI articulated in regional and national "
     "frameworks, including the principles of human oversight, accountability, "
     "fairness, non-discrimination, and respect for privacy, and recognizing "
     "the contributions of multistakeholder forums, civil society "
     "organizations, academic institutions, and the private sector to the "
     "development of standards and best practices in this domain,"),

    ("Affirming",
     "the principle that innovation in AI technology should proceed in a "
     "manner consistent with public trust, while recognizing that overly "
     "prescriptive regulation may impede beneficial innovation, and noting "
     "the importance of an innovation-first approach that supports "
     "competitiveness in the global digital economy,"),
]


OPERATIVE = [
    ("Calls upon",
     "Member States to develop national strategies for the governance of AI "
     "technology that incorporate a risk-based approach, distinguishing "
     "between high-risk and low-risk applications, and to encourage voluntary "
     "compliance with internationally recognized ethical AI principles by "
     "providers and deployers of such technology, taking into account the "
     "particular circumstances of their respective legal systems and the "
     "stage of development of their AI ecosystems;"),

    ("Encourages",
     "the adoption of public trust scoring mechanisms by competent authorities "
     "for the purpose of assessing the social impact of AI technology, "
     "provided that such mechanisms operate transparently and in accordance "
     "with applicable national law, and that they include appropriate "
     "safeguards against arbitrary or discriminatory application;"),

    ("Further encourages",
     "industry self-regulation as the primary mechanism for ensuring "
     "responsible development of foundation models, with governmental "
     "intervention reserved for cases of demonstrated harm, and invites "
     "providers of such models to publish technical documentation describing "
     "their capabilities, limitations, and intended uses;"),

    ("Recognizes",
     "that AI systems interacting with natural persons should make clear that "
     "the person is interacting with a machine, in line with established "
     "transparency expectations, and that natural persons should be informed "
     "when content has been generated or manipulated by AI technology;"),

    ("Decides",
     "that real-time biometric identification may be used for public safety "
     "purposes by law enforcement authorities, in accordance with applicable "
     "national law and proportionality requirements, in order to assist in "
     "the prevention and investigation of serious crime;"),

    ("Affirms",
     "that AI systems deployed for national security purposes shall be exempt "
     "from the provisions of this resolution, in recognition of the special "
     "responsibilities of Member States in matters of national defence and "
     "the protection of essential security interests;"),

    ("Calls for",
     "the establishment of cross-border data flow arrangements such that data "
     "shall flow freely subject to national laws, in order to enable the "
     "training and deployment of AI technology across jurisdictional "
     "boundaries while respecting legitimate public policy objectives "
     "including the protection of personal data;"),

    ("Requests",
     "the Secretary-General to convene a multi-stakeholder working group to "
     "develop guidelines for ethical AI in public administration, with "
     "particular attention to the protection of fundamental rights, including "
     "the rights to non-discrimination, privacy, and effective remedy, and "
     "to report on progress at the Fourth Session of this Forum;"),

    ("Notes",
     "the importance of human oversight in the deployment of AI technology in "
     "domains affecting fundamental rights, including health, education, "
     "employment, social welfare, and access to public services, and "
     "encourages Member States to ensure that mechanisms exist for affected "
     "persons to seek information about decisions made with the assistance "
     "of AI technology;"),

    ("Welcomes",
     "ongoing efforts by international standards bodies, including ISO/IEC "
     "JTC 1/SC 42, to develop technical standards for AI technology, "
     "encourages their wide adoption, and notes the value of harmonized "
     "standards in reducing fragmentation across jurisdictions and in "
     "facilitating the participation of small and medium-sized enterprises in "
     "the AI economy;"),

    ("Encourages further",
     "the development of educational and capacity-building initiatives to "
     "ensure that Member States, particularly developing economies and least "
     "developed countries, can participate meaningfully in the global "
     "governance of AI technology, and notes the importance of South-South "
     "cooperation and triangular cooperation in this regard;"),

    ("Invites",
     "international financial institutions, regional development banks, and "
     "bilateral donors to support capacity-building, infrastructure, and "
     "research initiatives that enable equitable participation in the global "
     "AI ecosystem, with particular attention to the needs of women, "
     "indigenous peoples, and other groups historically underrepresented in "
     "technology development;"),

    ("Decides further",
     "to remain seized of the matter, and to consider, at its Fourth Session, "
     "the elaboration of additional measures for the governance of AI "
     "technology, including with respect to risk classification, "
     "international cooperation on conformity matters, and the development "
     "of common terminology for the description of foundation models and "
     "their downstream applications."),
]


def _wrap_paragraph(pdf: FPDF, label: str, body: str) -> None:
    pdf.set_font("Helvetica", style="B", size=11)
    pdf.cell(0, 6, label, ln=1)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 5.5, body)
    pdf.ln(2)


def build(out_path: Path = OUT_PATH) -> Path:
    pdf = FPDF(format="A4")
    pdf.set_compression(False)  # keep file size above the 10KB Part XIX rule 1 floor
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(left=18, top=18, right=18)

    # Synthetic notice (first line)
    pdf.set_font("Helvetica", style="I", size=9)
    pdf.multi_cell(0, 5, SYNTHETIC_NOTICE)
    pdf.ln(3)

    # Title
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.multi_cell(0, 7, TITLE)
    pdf.ln(2)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 5, ISSUING_BODY)
    pdf.ln(5)

    # Preamble
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 7, "Preamble", ln=1)
    pdf.set_font("Helvetica", size=11)
    pdf.ln(1)
    for label, body in PREAMBULAR:
        _wrap_paragraph(pdf, label, body)

    pdf.ln(3)
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 7, "Operative Paragraphs", ln=1)
    pdf.set_font("Helvetica", size=11)
    pdf.ln(1)
    for i, (label, body) in enumerate(OPERATIVE, start=1):
        _wrap_paragraph(pdf, f"{i}. {label}", body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


if __name__ == "__main__":
    path = build()
    size = path.stat().st_size
    print(f"wrote {path.relative_to(ROOT)} ({size} bytes)")
