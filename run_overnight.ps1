# run_overnight.ps1 — unattended sequential RF-baseline pipeline.
#
# Stages (each resumable / skip-if-done): ingest -> clean -> lexicon -> features ->
# RF train + score (FULL corpus, window-first). Validated stages ONLY — no API-cost LLM jury
# calls and no (unreviewed) RoBERTa scoring; those are run attended.
#
# Fail-fast: if any stage exits non-zero, the run stops cleanly so we can resume.
# Re-running this script resumes (every stage skips already-completed work).
#
# Usage:  powershell -File run_overnight.ps1     (or launch in background)
# Progress log: C:\Users\jdamm\Caplan\overnight.log

$env:CAPLAN_ROOT       = "C:\Users\jdamm\Caplan\Caplan-Project"   # PRIMARY repo, moved out of Dropbox 2026-05-26 (Dropbox corrupted the working tree); data lives alongside at CAPLAN_DATA
$env:CAPLAN_DATA       = "C:\Users\jdamm\Caplan"
$env:CAPLAN_CLEAN_YEARS = "1895-1945,1770-1894,1946-1964"  # clean the FULL corpus, but window-FIRST (overnight #1 ran clean serial+ascending and burned the night on 1770-1869, never reaching the window). 02 now dispatches in this order, load-balanced.
$env:CAPLAN_SCORE_YEARS = "1895-1945,1770-1894,1946-1964"  # FULL corpus, window-FIRST: measure bias for EVERY year (the DiD only USES shock years 1895-1945, but scores are produced corpus-wide per the "whole thing" directive). Long-running but $0 API and resumable.
$ROOT = $env:CAPLAN_ROOT
$VPY  = "C:\Users\jdamm\Caplan\venv\Scripts\python.exe"
$RS   = "C:\Program Files\R\R-4.6.0\bin\Rscript.exe"
$LOG  = "C:\Users\jdamm\Caplan\overnight.log"

function Log($m) { ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) | Out-File -FilePath $LOG -Append -Encoding utf8 }

function RunR($rmd) {
  Log "START $rmd"
  & $RS -e "p<-knitr::purl(file.path(Sys.getenv('CAPLAN_ROOT'),'rmd/$rmd'),output=tempfile(fileext='.R'),documentation=0);source(p)" 2>&1 |
    Out-File -FilePath $LOG -Append -Encoding utf8
  if ($LASTEXITCODE -ne 0) { Log "FAILED $rmd (exit $LASTEXITCODE) -- stopping pipeline"; exit 1 }
  Log "DONE  $rmd"
}

Set-Location $ROOT
Log "=== OVERNIGHT RUN START ==="

Log "STAGE 1/5: ingest (all years, resumable)"
& $VPY (Join-Path $ROOT 'python\ingest_americanstories.py') --src $env:CAPLAN_DATA --out (Join-Path $env:CAPLAN_DATA 'data_parquet') --workers 8 2>&1 |
  Out-File -FilePath $LOG -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Log "ingest FAILED -- stopping"; exit 1 }
Log "DONE  ingest"

Log "STAGE 2/5: clean";                              RunR "02_clean_articles.Rmd"
Log "STAGE 3/5: lexicon scoring";                    RunR "06a_baseline_lexicon.Rmd"
Log "STAGE 4/5: TF-IDF/SVD features + transform";    RunR "06b_baseline_features.Rmd"
Log "STAGE 5/5: RF train + score FULL corpus (window-first)"; RunR "06c_baseline_rf.Rmd"

Log "=== OVERNIGHT RUN COMPLETE (RF-baseline pipeline) ==="
