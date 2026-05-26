"""Domain-specific corpus filler for the AI governance scenario.

Scenario helper: exempt from the no-domain-terms discipline gate (Part XIX
rule 6) by virtue of its filename prefix. Framework-level download
mechanics live in scripts/corpus_validator.py.

Behaviour:
  - Skip any target whose filename already exists in input/context/.
  - For pakistan_national_ai_2024.pdf only: if the existing file fails
    validate_corpus_entry (content-vs-filename match), delete it before
    re-download. Other pakistan-named files (PECA, PDP bill, UNDP, World
    Bank) are distinct documents and are left untouched.
  - Use download_with_fallback() for each target.
  - After the loop, run audit_corpus_directory() on the full context/.
  - Print final counts of downloaded / skipped / failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from corpus_validator import (
    audit_corpus_directory,
    download_with_fallback,
    validate_corpus_entry,
    validate_downloaded_file,
)


TARGETS: list[tuple[str, list[str]]] = [
    ("eu_ai_act_2024.pdf", [
        "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689",
    ]),
    ("us_executive_order_14110_2023.pdf", [
        "https://www.govinfo.gov/content/pkg/FR-2023-11-01/pdf/2023-24283.pdf",
        "https://www.govinfo.gov/content/pkg/CFR-2024-title3-vol1/pdf/CFR-2024-title3-vol1-eo14110.pdf",
    ]),
    ("china_genai_measures_2023.pdf", [
        "https://www.airuniversity.af.edu/Portals/10/CASI/documents/Translations/2023-08-07%20ITOW%20Interim%20Measures%20for%20the%20Management%20of%20Generative%20Artificial%20Intelligence%20Services.pdf",
    ]),
    ("canada_aida_bill_c27_2022.pdf", [
        "https://www.parl.ca/Content/Bills/441/Government/C-27/C-27_1/C-27_1.PDF",
    ]),
    ("australia_ai_framework_2024.pdf", [
        "https://www.finance.gov.au/sites/default/files/2024-06/National-framework-for-the-assurance-of-AI-in-government.pdf",
    ]),
    ("saudi_sdaia_ai_ethics_2023.pdf", [
        "https://sdaia.gov.sa/en/SDAIA/about/Documents/ai-principles.pdf",
        "https://dgp.sdaia.gov.sa/wps/wcm/connect/4c56ed1c-1b82-447d-ac29-638f5f99c12e/ai-principles-EN.pdf?MOD=AJPERES&CONVERT_TO=url&CACHEID=ROOTWORKSPACE-4c56ed1c-1b82-447d-ac29-638f5f99c12e-p3k51U9",
    ]),
    ("pakistan_national_ai_2024.pdf", [
        "https://moitt.gov.pk/SiteImage/Misc/files/National%20AI%20Policy.pdf",
        "https://moitt.gov.pk/SiteImage/Misc/files/National%20AI%20Policy%20Consultation%20Draft%20V1.pdf",
    ]),
    ("france_villani_report_2018.pdf", [
        "https://www.aiforhumanity.fr/pdfs/MissionVillani_Report_ENG-VF.pdf",
        "https://knowledge4policy.ec.europa.eu/sites/default/files/france-ai-strategy-report.pdf",
    ]),
    ("turkey_national_ai_2021.pdf", [
        "https://cbddo.gov.tr/SharedFolderServer/Genel/File/TRNationalAIStrategy2021-2025.pdf",
    ]),
    ("unesco_ai_ethics_rec_2021.pdf", [
        "https://unesdoc.unesco.org/ark:/48223/pf0000381137",
        "https://www.unesco.de/assets/dokumente/Deutsche_UNESCO-Kommission/02_Publikationen/Publikation_UNESCO_Recommendation_on_the_Ethics_of_Artificial_Intelligence.pdf",
    ]),
    ("japan_ai_strategy_2022.pdf", [
        "https://www8.cao.go.jp/cstp/ai/aistrategy2022_body_en.pdf",
    ]),
    ("india_niti_ai_strategy_2018.pdf", [
        "https://niti.gov.in/sites/default/files/2023-03/National-Strategy-for-Artificial-Intelligence.pdf",
    ]),
    ("germany_ai_strategy_2020.pdf", [
        "https://www.ki-strategie-deutschland.de/files/downloads/Fortschreibung_KI-Strategie_engl.pdf",
    ]),
    ("brazil_ebia_ai_strategy_2021.pdf", [
        "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/transformacaodigital/arquivosinteligenciaartificial/ebia-summary_brazilian_ai_strategy.pdf",
    ]),
]


def _handle_pakistan_collision(out_dir: Path) -> None:
    """Option C: delete pakistan_national_ai_2024.pdf only if it exists AND
    fails the content-vs-filename validator. Other pakistan-named files
    (separate, legitimate documents) are untouched."""
    target = out_dir / "pakistan_national_ai_2024.pdf"
    if not target.exists():
        return
    valid, _excerpt, _matched = validate_corpus_entry(target)
    if valid:
        return
    try:
        target.unlink()
        print(f"REPLACING {target.name} (failed content-vs-filename validation)",
              file=sys.stderr, flush=True)
    except OSError as e:
        print(f"WARN: could not delete {target}: {e}", file=sys.stderr, flush=True)


def main() -> int:
    out_dir = ROOT / "input" / "context"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_downloaded = 0
    n_skipped = 0
    failed: list[str] = []

    for filename, urls in TARGETS:
        if filename == "pakistan_national_ai_2024.pdf":
            _handle_pakistan_collision(out_dir)

        dest = out_dir / filename
        if dest.exists():
            print(f"SKIP {filename} (already present, {dest.stat().st_size} bytes)",
                  file=sys.stderr, flush=True)
            n_skipped += 1
            continue

        ok, winning_url, reason = download_with_fallback(urls, dest)
        if ok:
            size = dest.stat().st_size
            host = winning_url.split("/")[2] if "//" in winning_url else winning_url[:60]
            print(f"OK   {filename} <- {host} ({size} bytes)",
                  file=sys.stderr, flush=True)
            n_downloaded += 1
        else:
            print(f"FAIL {filename}: {reason}", file=sys.stderr, flush=True)
            failed.append(filename)

    # Full-corpus audit (old + new files) per Part XIX rule 2.
    audit = audit_corpus_directory(out_dir)
    n_mismatch = sum(1 for _, valid, _ in audit if not valid)

    print(
        f"\n=== final corpus summary ===\n"
        f"  downloaded this run: {n_downloaded}\n"
        f"  skipped (already present): {n_skipped}\n"
        f"  failed: {len(failed)}\n"
        f"  total PDFs in input/context/: {len(audit)}\n"
        f"  audit-flagged: {n_mismatch}",
        file=sys.stderr, flush=True,
    )
    if failed:
        print(f"  failed filenames: {failed}", file=sys.stderr, flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
