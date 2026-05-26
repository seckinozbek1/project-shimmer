"""Download the 50-document AI-governance corpus into input/context/.

Strategy per document:
  1. Try a curated URL list (the most likely official source)
  2. If 404 / wrong content type, fall back to the next URL
  3. Verify the response is a PDF (Content-Type or magic bytes) before saving

Reports which documents succeeded and which fell through. Operator can re-run
to retry the gaps.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


CORPUS: list[dict] = [
    # Multilateral frameworks
    {"slug": "eu_ai_act_2024", "title": "EU AI Act (Regulation 2024/1689)",
     "urls": [
         "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689",
         "https://eur-lex.europa.eu/resource.html?uri=cellar:e0649735-a372-11eb-9585-01aa75ed71a1.0001.02/DOC_1&format=PDF",
     ]},
    {"slug": "oecd_ai_principles_2019", "title": "OECD AI Principles (2019)",
     "urls": [
         "https://legalinstruments.oecd.org/api/print?ids=648&lang=en",
         "https://www.oecd.org/digital/forty-two-countries-adopt-new-oecd-principles-on-artificial-intelligence.htm",
     ]},
    {"slug": "unesco_ethics_ai_2021", "title": "UNESCO Recommendation on the Ethics of AI (2021)",
     "urls": [
         "https://unesdoc.unesco.org/ark:/48223/pf0000381137/PDF/381137eng.pdf.multi",
         "https://unesdoc.unesco.org/ark:/48223/pf0000380455",
     ]},
    {"slug": "coe_framework_convention_ai_2024", "title": "Council of Europe Framework Convention on AI (2024)",
     "urls": [
         "https://rm.coe.int/1680afae3c",
         "https://www.coe.int/en/web/artificial-intelligence/the-framework-convention-on-artificial-intelligence",
     ]},
    {"slug": "gpai_2023_report", "title": "GPAI Annual Report 2023",
     "urls": [
         "https://gpai.ai/projects/gpai-2023-annual-report.pdf",
         "https://gpai.ai/projects/responsible-ai/social-media-governance/social-media-governance-project-report.pdf",
     ]},
    {"slug": "g7_hiroshima_ai_2023", "title": "G7 Hiroshima Process International Guiding Principles (2023)",
     "urls": [
         "https://www.mofa.go.jp/files/100573471.pdf",
         "https://digital-strategy.ec.europa.eu/en/library/g7-leaders-statement-hiroshima-ai-process",
     ]},
    {"slug": "g20_ai_principles_2019", "title": "G20 AI Principles (2019, from OECD)",
     "urls": [
         "https://www.mofa.go.jp/files/000486596.pdf",
         "https://www.g20-insights.org/wp-content/uploads/2017/03/Briefing-Note_G20-AI-Principles.pdf",
     ]},
    {"slug": "un_ai_advisory_body_final_2024", "title": "UN Secretary-General Advisory Body on AI — Governing AI for Humanity (2024)",
     "urls": [
         "https://www.un.org/sites/un2.un.org/files/governing_ai_for_humanity_final_report_en.pdf",
         "https://www.un.org/sites/un2.un.org/files/ai_advisory_body_interim_report.pdf",
     ]},
    {"slug": "itu_ai_for_good_2023", "title": "ITU AI for Good Innovate for Impact Report 2023",
     "urls": [
         "https://www.itu.int/dms_pub/itu-s/opb/gen/S-GEN-AIIMPACT-2023-PDF-E.pdf",
         "https://www.itu.int/dms_pub/itu-s/opb/gen/S-GEN-AI4GOOD-2023-PDF-E.pdf",
     ]},
    {"slug": "wef_ai_governance_2024", "title": "WEF AI Governance Alliance White Paper",
     "urls": [
         "https://www3.weforum.org/docs/WEF_Generative_AI_Governance_2024.pdf",
         "https://www3.weforum.org/docs/WEF_Responsible_AI_Playbook_for_Investors_2024.pdf",
     ]},
    # National strategies and legislation
    {"slug": "us_eo_14110_2023", "title": "US Executive Order 14110 on AI Safety (Oct 2023)",
     "urls": [
         "https://www.federalregister.gov/documents/2023/11/01/2023-24283/safe-secure-and-trustworthy-development-and-use-of-artificial-intelligence",
         "https://www.whitehouse.gov/wp-content/uploads/2023/10/Executive-Order-14110.pdf",
     ]},
    {"slug": "nist_ai_rmf_2023", "title": "NIST AI Risk Management Framework 1.0 (2023)",
     "urls": [
         "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
         "https://www.nist.gov/itl/ai-risk-management-framework",
     ]},
    {"slug": "china_genai_measures_2023", "title": "China Interim Measures for Generative AI Services (2023)",
     "urls": [
         "https://www.chinalawtranslate.com/en/generative-ai-interim/",
         "https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm",
     ]},
    {"slug": "china_deep_synthesis_2022", "title": "China Deep Synthesis Provisions (2022)",
     "urls": [
         "https://www.chinalawtranslate.com/en/deep-synthesis/",
         "https://digichina.stanford.edu/work/translation-internet-information-service-deep-synthesis-management-provisions/",
     ]},
    {"slug": "singapore_model_ai_2020", "title": "Singapore Model AI Governance Framework (2020)",
     "urls": [
         "https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/resource-for-organisation/ai/sgmodelaigovframework2.pdf",
         "https://file.go.gov.sg/aiverify.pdf",
     ]},
    {"slug": "singapore_pdp_ai_2024", "title": "Singapore Advisory Guidelines on Use of Personal Data in AI (2024)",
     "urls": [
         "https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/advisory-guidelines-on-the-use-of-personal-data-in-ai-recommendation-and-decision-systems.pdf",
         "https://www.pdpc.gov.sg/guidelines-and-consultation/2024/02/advisory-guidelines-on-use-of-personal-data-in-ai",
     ]},
    {"slug": "brazil_pl_2338_2023", "title": "Brazil AI Regulation Bill PL 2338/2023",
     "urls": [
         "https://www25.senado.leg.br/web/atividade/materias/-/materia/157233",
         "https://legis.senado.leg.br/sdleg-getter/documento?dm=9347622&disposition=inline",
     ]},
    {"slug": "canada_aida_2022", "title": "Canada Artificial Intelligence and Data Act (Bill C-27)",
     "urls": [
         "https://www.parl.ca/DocumentViewer/en/44-1/bill/C-27/first-reading",
         "https://ised-isde.canada.ca/site/innovation-better-canada/sites/default/files/attachments/2022/aida-companion-document-en.pdf",
     ]},
    {"slug": "japan_ai_strategy_2022", "title": "Japan AI Strategy 2022",
     "urls": [
         "https://www8.cao.go.jp/cstp/ai/aistratagy2022en.pdf",
         "https://www8.cao.go.jp/cstp/ai/index.html",
     ]},
    {"slug": "korea_ai_basic_act_2025", "title": "South Korea AI Basic Act (Framework Act on AI Development and Trust, 2024-2025)",
     "urls": [
         "https://www.korea.kr/common/download.do?fileId=197053442",
         "https://elaw.klri.re.kr/eng_service/lawView.do?hseq=53593",
     ]},
    {"slug": "india_niti_responsible_ai_2021", "title": "India NITI Aayog — Responsible AI Approach Document (2021)",
     "urls": [
         "https://www.niti.gov.in/sites/default/files/2021-02/Responsible-AI-22022021.pdf",
         "https://www.niti.gov.in/sites/default/files/2021-08/Part2-Responsible-AI-12082021.pdf",
     ]},
    {"slug": "australia_ai_ethics_2019", "title": "Australia AI Ethics Framework (2019)",
     "urls": [
         "https://www.industry.gov.au/sites/default/files/2019-11/australias-ai-ethics-framework-2019.pdf",
         "https://www.industry.gov.au/data-and-publications/australias-artificial-intelligence-ethics-framework",
     ]},
    {"slug": "uk_aisi_2024", "title": "UK AI Safety Institute Approach (2024)",
     "urls": [
         "https://www.aisi.gov.uk/work/our-approach",
         "https://assets.publishing.service.gov.uk/media/65395abae6c968000daa9b25/advanced-ai-evaluations-may-update.pdf",
     ]},
    {"slug": "uk_white_paper_ai_2023", "title": "UK Pro-Innovation AI Regulation White Paper (2023)",
     "urls": [
         "https://assets.publishing.service.gov.uk/media/64cb71a547915a00142a91c4/a-pro-innovation-approach-to-ai-regulation-amended-web-ready.pdf",
         "https://www.gov.uk/government/publications/ai-regulation-a-pro-innovation-approach",
     ]},
    {"slug": "germany_ai_strategy_2020", "title": "Germany AI Strategy Update (2020)",
     "urls": [
         "https://www.ki-strategie-deutschland.de/files/downloads/Fortschreibung_KI-Strategie_engl.pdf",
         "https://www.ki-strategie-deutschland.de/files/downloads/201201_Fortschreibung_KI-Strategie.pdf",
     ]},
    {"slug": "france_ai_strategy_2024", "title": "France AI Strategy / Comité IA Generative Report (2024)",
     "urls": [
         "https://www.economie.gouv.fr/files/files/2024/IA-rapport-comite-IA-generative.pdf",
         "https://www.economie.gouv.fr/files/2024-03/Rapport_Commission_IA_v2.pdf",
     ]},
    {"slug": "uae_ai_strategy_2031", "title": "UAE National AI Strategy 2031",
     "urls": [
         "https://ai.gov.ae/wp-content/uploads/2021/07/UAE-National-Strategy-for-Artificial-Intelligence-2031.pdf",
         "https://u.ae/-/media/Documents-2021/UAE-National-Strategy-for-Artificial-Intelligence-2031.ashx",
     ]},
    {"slug": "saudi_sdaia_principles_2023", "title": "SDAIA AI Ethics Principles (Saudi Arabia, 2023)",
     "urls": [
         "https://sdaia.gov.sa/en/SDAIA/about/Files/AIEthicsPrinciples_eng.pdf",
         "https://sdaia.gov.sa/en/SDAIA/about/Files/PreviewPolicyDocument.pdf",
     ]},
    {"slug": "rwanda_national_ai_2023", "title": "Rwanda National AI Policy (2023)",
     "urls": [
         "https://www.minict.gov.rw/index.php?eID=dumpFile&t=f&f=67550&token=6195a53203e197efa47592f40ffdcf1b9d595a1d",
         "https://rura.rw/fileadmin/user_upload/Documents/policies/Rwanda_AI_Policy.pdf",
     ]},
    {"slug": "kenya_draft_ai_2023", "title": "Kenya Draft National AI Strategy (2023)",
     "urls": [
         "https://www.ict.go.ke/wp-content/uploads/2024/01/National-AI-Strategy-Kenya.pdf",
         "https://ict.go.ke/wp-content/uploads/2024/05/THE-KENYA-AI-STRATEGY-2025-2030-1.pdf",
     ]},
    {"slug": "nigeria_national_ai_2024", "title": "Nigeria National AI Strategy (2024)",
     "urls": [
         "https://ncair.nitda.gov.ng/wp-content/uploads/2024/08/National-AI-Strategy_01082024-copy.pdf",
         "https://ncair.nitda.gov.ng/national-ai-strategy/",
     ]},
    {"slug": "south_africa_ai_2024", "title": "South Africa National AI Policy Framework (2024)",
     "urls": [
         "https://www.dcdt.gov.za/images/SA-AI-Policy-Framework_2024.pdf",
         "https://www.gov.za/sites/default/files/gcis_document/202404/national-artificial-intelligence-policy-framework.pdf",
     ]},
    {"slug": "au_ai_continental_2024", "title": "African Union AI Continental Strategy (2024)",
     "urls": [
         "https://au.int/sites/default/files/documents/44004-doc-EN-_Continental_AI_Strategy_July_2024.pdf",
         "https://au.int/en/documents/20240809/african-union-continental-artificial-intelligence-strategy",
     ]},
    {"slug": "mexico_ai_strategy_2024", "title": "Mexico National AI Strategy / Agenda 2024",
     "urls": [
         "https://www.gob.mx/cms/uploads/attachment/file/942234/Agenda_Nacional_IA_Mexico_2024.pdf",
         "https://www.ia2030.mx/wp-content/uploads/2023/12/Estrategia-Nacional-IA-2024.pdf",
     ]},
    {"slug": "colombia_ai_ethics_2024", "title": "Colombia AI Ethics Framework (Marco Ético IA, 2024)",
     "urls": [
         "https://gobiernodigital.mintic.gov.co/692/articles-249713_recurso_1.pdf",
         "https://gobiernodigital.mintic.gov.co/portal/Iniciativas/Inteligencia-Artificial/",
     ]},
    {"slug": "chile_national_ai_2021", "title": "Chile National AI Policy (2021)",
     "urls": [
         "https://www.minciencia.gob.cl/uploads/filer_public/aa/61/aa61c52d-9e29-4ba1-a900-f3f6c8df8a51/22102021_pnia_eng.pdf",
         "https://www.minciencia.gob.cl/areas/inteligencia-artificial/politica-nacional-de-ia/",
     ]},
    {"slug": "israel_ai_policy_2023", "title": "Israel National AI Policy Principles (2023)",
     "urls": [
         "https://www.gov.il/BlobFolder/news/ai-2023/en/AI_POLICY_eng.pdf",
         "https://www.gov.il/en/departments/policies/policy_for_responsible_artificial_intelligence_2023",
     ]},
    {"slug": "turkey_national_ai_2021", "title": "Turkey National AI Strategy 2021-2025",
     "urls": [
         "https://cbddo.gov.tr/SharedFolderServer/Genel/File/TR-NationalAIStrategy2021-2025.pdf",
         "https://cbddo.gov.tr/en/national-ai-strategy/",
     ]},
    {"slug": "indonesia_stranas_ka_2020", "title": "Indonesia Stranas KA — National AI Strategy 2020-2045",
     "urls": [
         "https://ai-innovation.id/server/static/ebook/Strategi-Nasional-Kecerdasan-Artifisial.pdf",
         "https://ai-innovation.id/strategi-nasional",
     ]},
    # OIC / Islamic ethics intersection
    {"slug": "oic_digital_dec_2022", "title": "OIC Standing Committee for Scientific and Technological Cooperation — Digital Declaration (2022)",
     "urls": [
         "https://www.comstech.org/wp-content/uploads/2022/01/COMSTECH-Declaration-on-Digital-Innovation-2022.pdf",
         "https://www.comstech.org/declarations/",
     ]},
    {"slug": "isdb_digital_economy_2023", "title": "Islamic Development Bank — Digital Economy Working Paper (2023)",
     "urls": [
         "https://www.isdb.org/sites/default/files/media/documents/2023-05/Digital-Economy-WP-2023.pdf",
         "https://www.isdb.org/news/isdb-launches-its-digital-transformation-strategy",
     ]},
    {"slug": "scholarly_islamic_ai_ethics", "title": "Scholarly note: Islamic Ethics and AI Governance",
     "urls": [
         "https://www.iais.org.my/attach/Vol43-44/IAIS-Journal-Volume-44.pdf",
         "https://yaqeeninstitute.org/read/paper/ai-and-islamic-ethics",
     ]},
    {"slug": "pakistan_peca_2016", "title": "Pakistan Prevention of Electronic Crimes Act, 2016",
     "urls": [
         "https://nasirlawsite.com/laws/peca.pdf",
         "https://moitt.gov.pk/SiteImage/Misc/files/PECA-ACT-2016.pdf",
     ]},
    {"slug": "pakistan_pdp_bill_draft", "title": "Pakistan Personal Data Protection Bill (latest draft)",
     "urls": [
         "https://moitt.gov.pk/SiteImage/Misc/files/Personal%20Data%20Protection%20Bill%202023.pdf",
         "https://moitt.gov.pk/SiteImage/Misc/files/Personal_Data_Protection_Bill_2021.pdf",
     ]},
    # Recent (intended to fall after the 2024-01-01 cutoff)
    {"slug": "pakistan_national_ai_2024", "title": "Pakistan National AI Policy Draft (Ministry of IT, 2024)",
     "urls": [
         "https://moitt.gov.pk/SiteImage/Misc/files/National%20AI%20Policy%20Consulation%20Draft%20V1.pdf",
         "https://moitt.gov.pk/SiteImage/Misc/files/AI%20Policy%20Draft%20V1.pdf",
     ]},
    {"slug": "undp_pakistan_digital_2024", "title": "UNDP Pakistan Digital Readiness Assessment (2024)",
     "urls": [
         "https://www.undp.org/sites/g/files/zskgke326/files/2024-06/digital_readiness_assessment_pakistan_2024.pdf",
         "https://www.undp.org/pakistan/publications/digital-readiness-assessment",
     ]},
    {"slug": "wb_digital_pakistan_2024", "title": "World Bank Digital Pakistan / South Asia AI Assessment (2024)",
     "urls": [
         "https://documents1.worldbank.org/curated/en/099072524131517090/pdf/IDU-d4d18e58-3654-4cae-95e2-37a4866f0b08.pdf",
         "https://openknowledge.worldbank.org/server/api/core/bitstreams/13c3e7ce-1b8d-4cda-bc4a-13e30a8c8db4/content",
     ]},
    {"slug": "asean_ai_guide_2024", "title": "ASEAN Guide on AI Governance and Ethics (2024)",
     "urls": [
         "https://asean.org/wp-content/uploads/2024/02/ASEAN-Guide-on-AI-Governance-and-Ethics_beautified_201223_v2.pdf",
         "https://asean.org/wp-content/uploads/2024/06/ASEAN-Guide-AIGE-Generative-AI_final.pdf",
     ]},
    {"slug": "adb_digital_dev_2024", "title": "ADB AI for Developing Economies (2024)",
     "urls": [
         "https://www.adb.org/sites/default/files/publication/918946/asian-economic-integration-report-2024.pdf",
         "https://www.adb.org/sites/default/files/publication/990946/digital-public-infrastructure-asia.pdf",
     ]},
    {"slug": "un_ga_res_ai_2024", "title": "UN General Assembly Resolution on AI (A/RES/78/265, 2024)",
     "urls": [
         "https://documents.un.org/api/symbol/access?s=A/RES/78/265&l=en&t=pdf",
         "https://undocs.org/A/RES/78/265",
     ]},
]


def _is_pdf(blob: bytes, content_type: str) -> bool:
    if blob.startswith(b"%PDF-"):
        return True
    return "application/pdf" in (content_type or "").lower()


def _download_one(slug: str, urls: list[str], out_path: Path,
                  timeout: int = 60, user_agent: str = "Shimmer/0.1") -> tuple[bool, str]:
    if out_path.exists() and out_path.stat().st_size > 1024:
        return True, f"already present ({out_path.stat().st_size} bytes)"
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                                       "Accept": "application/pdf,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                blob = resp.read()
        except Exception as e:
            yield_msg = f"{url[:80]}: {type(e).__name__}: {str(e)[:80]}"
            continue
        if not blob:
            continue
        if _is_pdf(blob, content_type):
            out_path.write_bytes(blob)
            return True, f"OK from {url[:80]} ({len(blob)} bytes, {content_type})"
        # Else: not a PDF (probably HTML); try next URL
    return False, f"all {len(urls)} URLs returned non-PDF or failed"


def main(argv=None):
    project_root = Path(__file__).resolve().parent.parent
    out_dir = project_root / "input" / "context"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    print(f"[corpus] target dir: {out_dir}", file=sys.stderr)
    for i, doc in enumerate(CORPUS, 1):
        slug = doc["slug"]
        out_path = out_dir / f"{slug}.pdf"
        ok, msg = _download_one(slug, doc["urls"], out_path)
        results.append({"slug": slug, "title": doc["title"], "ok": ok, "msg": msg,
                        "path": str(out_path) if ok else None})
        marker = "OK " if ok else "MISS"
        print(f"[{i:2d}/{len(CORPUS)}] {marker} {slug}: {msg[:140]}", file=sys.stderr, flush=True)
        time.sleep(0.5)  # be polite to servers
    n_ok = sum(1 for r in results if r["ok"])
    print(f"\n[corpus] {n_ok}/{len(CORPUS)} documents acquired", file=sys.stderr)
    manifest_path = out_dir / "_download_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
